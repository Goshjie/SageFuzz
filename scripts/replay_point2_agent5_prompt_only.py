from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agno.agent import Agent
from agno.models.dashscope import DashScope
from sagefuzz_seedgen.schemas import CriticResult


TASKS = {
    "firewall": "2026-03-07T064109Z",
    "link_monitor": "2026-03-07T070712Z",
    "fast_reroute": "2026-03-07T053017Z",
}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _read_small_model() -> DashScope:
    lines = (ROOT / "tests" / "test_littlellm.py").read_text(encoding="utf-8").splitlines()

    def capture(name: str) -> str:
        pattern = re.compile(rf'{name}\s*=\s*"([^"]+)"')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = pattern.search(stripped)
            if match:
                return match.group(1)
        raise RuntimeError(f"Unable to parse active {name} from test_littlellm.py")

    model_id = os.getenv("POINT2_MODEL_ID") or capture("id")
    api_key = os.getenv("POINT2_API_KEY") or capture("api_key")
    base_url = os.getenv("POINT2_BASE_URL") or capture("base_url")
    return DashScope(
        id=model_id,
        api_key=api_key,
        base_url=base_url,
        timeout=60,
        max_retries=1,
    )


def _sample_path(run_id: str) -> Path:
    base = ROOT / "runs" / "agent_responses" / run_id / "agent5_entity_critic"
    matches = sorted(base.glob("entity_critic_result_*_01.json"))
    if not matches:
        raise FileNotFoundError(f"No Agent5 sample under {base}")
    return matches[0]


def main() -> int:
    model = _read_small_model()
    prompt_md = (ROOT / "prompts" / "agent5_entity_critic.md").read_text(encoding="utf-8")
    out_dir = ROOT / "runs" / f"point2_agent5_prompt_only_{_utc_ts()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for task, run_id in TASKS.items():
        sample_path = _sample_path(run_id)
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        model_input = payload["input"]
        agent = Agent(
            name=f"agent5-{task}",
            model=model,
            markdown=False,
            use_json_mode=True,
            instructions=prompt_md,
        )
        prompt = "Evaluate control-plane entities and return CriticResult STRICT JSON:\n\n" + json.dumps(
            model_input, ensure_ascii=False, indent=2
        )
        result: Dict[str, Any] = {
            "task": task,
            "sample_path": str(sample_path.relative_to(ROOT)),
        }
        start = time.perf_counter()
        try:
            response = agent.run(prompt, output_schema=CriticResult)
            content = response.content
            if isinstance(content, CriticResult):
                result["status"] = "success"
                result["content"] = content.model_dump()
            else:
                result["status"] = "invalid_output"
                result["content"] = str(content)
        except Exception as exc:
            result["status"] = "error"
            result["error_type"] = exc.__class__.__name__
            result["error"] = str(exc)
        result["duration_seconds_wall"] = time.perf_counter() - start
        results.append(result)
        print(json.dumps({"task": task, "status": result["status"]}, ensure_ascii=False), flush=True)

    (out_dir / "results.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Point-2 Agent5 Prompt-Only Results",
        "",
        "| Task | Status | Wall(s) | Note |",
        "| --- | --- | ---: | --- |",
    ]
    for item in results:
        note = item.get("error") or json.dumps(item.get("content", {}), ensure_ascii=False)[:140]
        lines.append(
            f"| {item['task']} | {item['status']} | {float(item.get('duration_seconds_wall', 0.0)):.2f} | {note.replace('|', '/')} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[point2-agent5] results saved to {out_dir.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
