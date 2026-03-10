from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

TASKS = ["firewall", "link_monitor", "fast_reroute"]
AGENTS = ["agent1", "agent2", "agent4", "agent5"]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def main() -> int:
    out_dir = ROOT / "runs" / f"point2_agent_replays_{_utc_ts()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for task in TASKS:
        for agent in AGENTS:
            cmd = [
                str(ROOT / ".venv" / "bin" / "python"),
                str(ROOT / "scripts" / "replay_point2_single_sample.py"),
                task,
                agent,
            ]
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    text=True,
                    capture_output=True,
                    timeout=180,
                )
                if completed.stdout.strip():
                    payload = None
                    for line in reversed(completed.stdout.strip().splitlines()):
                        stripped = line.strip()
                        if stripped.startswith("{") and stripped.endswith("}"):
                            payload = json.loads(stripped)
                            break
                    if payload is None:
                        payload = {
                            "task": task,
                            "agent": agent,
                            "status": "error",
                            "error_type": "InvalidStdout",
                            "error": completed.stdout.strip()[-500:],
                        }
                else:
                    payload = {
                        "task": task,
                        "agent": agent,
                        "status": "error",
                        "error_type": "NoOutput",
                        "error": completed.stderr.strip() or "No stdout produced.",
                    }
            except subprocess.TimeoutExpired:
                payload = {
                    "task": task,
                    "agent": agent,
                    "status": "timeout",
                    "error_type": "TimeoutExpired",
                    "error": "Replay exceeded 180 seconds.",
                }

            results.append(payload)
            print(json.dumps({"task": task, "agent": agent, "status": payload["status"]}, ensure_ascii=False), flush=True)

    (out_dir / "results.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Point-2 Agent Replay Results",
        "",
        "| Task | Agent | Status | Wall(s) | Note |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in results:
        note = item.get("error") or json.dumps(item.get("content", {}), ensure_ascii=False)[:140]
        lines.append(
            f"| {item['task']} | {item['agent']} | {item['status']} | {float(item.get('duration_seconds_wall', 0.0)):.2f} | {note.replace('|', '/')} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[point2-replay] results saved to {out_dir.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
