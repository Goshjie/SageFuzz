from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_point2_experiments import TASKS, _read_baseline_model, _read_small_model, _run_one


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def main() -> int:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    experiment_dir = ROOT / "runs" / f"point2_firewall_repeats_{_utc_ts()}"
    experiment_dir.mkdir(parents=True, exist_ok=True)

    baseline_model = _read_baseline_model()
    small_model = _read_small_model()
    firewall_task = next(task for task in TASKS if task.name == "firewall")

    results: List[Dict[str, Any]] = []
    for round_id in range(1, repeats + 1):
        for mode in ("baseline", "agent5_small", "all_small"):
            print(f"[repeat-firewall] round={round_id} mode={mode}", flush=True)
            item = _run_one(
                task=firewall_task,
                mode=mode,
                experiment_dir=experiment_dir,
                baseline_model=baseline_model,
                small_model=small_model,
            )
            item["round"] = round_id
            results.append(item)
            print(
                json.dumps(
                    {
                        "round": round_id,
                        "mode": mode,
                        "returncode": item["returncode"],
                        "summary": item["summary"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    payload = {
        "baseline_model": {
            "model_id": baseline_model["model_id"],
            "base_url": baseline_model["base_url"],
        },
        "small_model": {
            "model_id": small_model["model_id"],
            "base_url": small_model["base_url"],
        },
        "results": results,
    }
    (experiment_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Firewall Repeat Experiment Results",
        "",
        f"- `baseline_model`: `{baseline_model['model_id']}`",
        f"- `small_model`: `{small_model['model_id']}`",
        "",
        "| Round | Mode | Return | Final | PacketSeq | Attempts | Passed | OracleFallback | Wall(s) | Index |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        summary = item["summary"]
        lines.append(
            "| {round} | {mode} | {returncode} | {final_status} | {packet_status} | {attempts} | {passed} | {oracle_fallback} | {wall:.2f} | `{index}` |".format(
                round=item["round"],
                mode=item["mode"],
                returncode=item["returncode"],
                final_status=summary.get("final_status"),
                packet_status=summary.get("packet_sequence_status"),
                attempts=summary.get("attempts_packet_sequence"),
                passed=summary.get("passed_case_count"),
                oracle_fallback=summary.get("oracle_prediction_fallback_case_count"),
                wall=item["duration_seconds_wall"],
                index=item["index_path"],
            )
        )
    (experiment_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[repeat-firewall] results saved to {experiment_dir.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
