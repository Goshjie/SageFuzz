from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs" / "agent_responses"
OUT_ROOT = ROOT / "runs" / "training_datasets"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _safe_get(d: Dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _infer_family(*, user_intent: Dict[str, Any], task: Optional[Dict[str, Any]]) -> str:
    category = str((task or {}).get("intent_category") or "").strip().lower()
    if category:
        if category in {"telemetry_monitoring", "state_observation"}:
            return "telemetry_monitoring"
        if category == "load_distribution":
            return "load_distribution_congestion_feedback"
        if category == "stateful_policy":
            return "threshold_state_accumulation"
        return category

    joined = " ".join(
        [
            str(user_intent.get("intent_text") or ""),
            str(user_intent.get("feature_under_test") or ""),
            str(user_intent.get("traffic_pattern") or ""),
            str(user_intent.get("operator_constraints") or ""),
        ]
    ).lower()
    if any(token in joined for token in ("probe", "telemetry", "monitor", "监控", "观测", "利用率")):
        return "telemetry_monitoring"
    if any(token in joined for token in ("heavy hitter", "threshold", "阈值", "计数", "累计")):
        return "threshold_state_accumulation"
    if any(token in joined for token in ("load balancing", "load balance", "负载均衡", "ecmp", "拥塞", "反馈")):
        return "load_distribution_congestion_feedback"
    return "other"


def _serialize_prompt(
    *,
    user_intent: Dict[str, Any],
    candidate_task: Optional[Dict[str, Any]],
    critic_feedback: Optional[str],
    family: str,
    source_kind: str,
) -> str:
    payload = {
        "task": "Repair or complete a TaskSpec for fallback execution.",
        "family": family,
        "source_kind": source_kind,
        "user_intent": user_intent,
        "candidate_task": candidate_task,
        "critic_feedback": critic_feedback,
        "requirements": [
            "Return a complete TaskSpec JSON only.",
            "Preserve user intent while making the task executable.",
            "Use explicit scenarios, role bindings, and observation/operator fields when needed.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class DatasetSample:
    sample_id: str
    run_id: str
    family: str
    source_kind: str
    user_intent: Dict[str, Any]
    candidate_task: Optional[Dict[str, Any]]
    critic_feedback: Optional[str]
    target_task: Dict[str, Any]
    provenance: Dict[str, Any]

    def to_record(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "run_id": self.run_id,
            "family": self.family,
            "source_kind": self.source_kind,
            "user_intent": self.user_intent,
            "candidate_task": self.candidate_task,
            "critic_feedback": self.critic_feedback,
            "target_task": self.target_task,
            "prompt": _serialize_prompt(
                user_intent=self.user_intent,
                candidate_task=self.candidate_task,
                critic_feedback=self.critic_feedback,
                family=self.family,
                source_kind=self.source_kind,
            ),
            "completion": json.dumps(self.target_task, ensure_ascii=False, indent=2),
            "provenance": self.provenance,
        }


def _find_initial_intent(run_dir: Path) -> Optional[Dict[str, Any]]:
    path = run_dir / "agent1_semantic_analyzer" / "initial_intent_intake_00.json"
    obj = _load_json(path)
    if not obj:
        return None
    value = _safe_get(obj, "output", "user_intent")
    return value if isinstance(value, dict) else None


def _latest_agent1_task(run_dir: Path) -> Optional[Dict[str, Any]]:
    agent_dir = run_dir / "agent1_semantic_analyzer"
    if not agent_dir.exists():
        return None
    paths = sorted(agent_dir.glob("agent1_output_*.json"))
    for path in reversed(paths):
        obj = _load_json(path)
        if not obj:
            continue
        output = obj.get("output")
        if isinstance(output, dict) and output.get("kind") == "task" and isinstance(output.get("task"), dict):
            return output["task"]
    return None


def _latest_task_review_feedback(run_dir: Path) -> Optional[str]:
    review_dir = run_dir / "agent3_constraint_critic"
    if not review_dir.exists():
        return None
    paths = sorted(review_dir.glob("task_contract_review_*.json"))
    for path in reversed(paths):
        obj = _load_json(path)
        if not obj:
            continue
        output = obj.get("output")
        if isinstance(output, dict) and isinstance(output.get("feedback"), str):
            return output["feedback"]
    det_dir = run_dir / "deterministic_validator"
    det_paths = sorted(det_dir.glob("task_contract_review_fallback_accept_*.json")) if det_dir.exists() else []
    for path in reversed(det_paths):
        obj = _load_json(path)
        if not obj:
            continue
        output = obj.get("output")
        if isinstance(output, dict) and isinstance(output.get("feedback"), str):
            return output["feedback"]
    return None


def _collect_fallback_samples(run_dir: Path) -> List[DatasetSample]:
    samples: List[DatasetSample] = []
    run_id = run_dir.name
    user_intent = _find_initial_intent(run_dir)
    if not user_intent:
        return samples

    det_dir = run_dir / "deterministic_validator"
    if not det_dir.exists():
        return samples

    fallback_paths = sorted(det_dir.glob("task_contract_fallback_from_intent_*.json"))
    for path in fallback_paths:
        obj = _load_json(path)
        if not obj:
            continue
        output = obj.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("task"), dict):
            continue
        target_task = output["task"]
        family = _infer_family(user_intent=user_intent, task=target_task)
        candidate_task = _latest_agent1_task(run_dir)
        critic_feedback = _latest_task_review_feedback(run_dir)
        samples.append(
            DatasetSample(
                sample_id=f"{run_id}::fallback::{path.stem}",
                run_id=run_id,
                family=family,
                source_kind="task_contract_fallback_from_intent",
                user_intent=user_intent,
                candidate_task=candidate_task,
                critic_feedback=critic_feedback,
                target_task=target_task,
                provenance={
                    "run_dir": str(run_dir.relative_to(ROOT)),
                    "fallback_path": str(path.relative_to(ROOT)),
                },
            )
        )
    return samples


def _collect_review_accept_samples(run_dir: Path) -> List[DatasetSample]:
    samples: List[DatasetSample] = []
    run_id = run_dir.name
    user_intent = _find_initial_intent(run_dir)
    if not user_intent:
        return samples

    det_dir = run_dir / "deterministic_validator"
    if not det_dir.exists():
        return samples

    review_paths = sorted(det_dir.glob("task_contract_review_fallback_accept_*.json"))
    for path in review_paths:
        obj = _load_json(path)
        if not obj:
            continue
        task = _safe_get(obj, "input", "task")
        feedback = _safe_get(obj, "output", "feedback")
        if not isinstance(task, dict):
            continue
        family = _infer_family(user_intent=user_intent, task=task)
        samples.append(
            DatasetSample(
                sample_id=f"{run_id}::review_accept::{path.stem}",
                run_id=run_id,
                family=family,
                source_kind="task_contract_review_fallback_accept",
                user_intent=user_intent,
                candidate_task=_latest_agent1_task(run_dir),
                critic_feedback=feedback if isinstance(feedback, str) else None,
                target_task=task,
                provenance={
                    "run_dir": str(run_dir.relative_to(ROOT)),
                    "review_accept_path": str(path.relative_to(ROOT)),
                },
            )
        )
    return samples


def _collect_direct_task_samples(run_dir: Path) -> List[DatasetSample]:
    samples: List[DatasetSample] = []
    run_id = run_dir.name
    user_intent = _find_initial_intent(run_dir)
    if not user_intent:
        return samples

    agent_dir = run_dir / "agent1_semantic_analyzer"
    if not agent_dir.exists():
        return samples

    paths = sorted(agent_dir.glob("agent1_output_*.json"))
    for path in paths:
        obj = _load_json(path)
        if not obj:
            continue
        output = obj.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("kind") != "task" or not isinstance(output.get("task"), dict):
            continue
        target_task = output["task"]
        family = _infer_family(user_intent=user_intent, task=target_task)
        samples.append(
            DatasetSample(
                sample_id=f"{run_id}::direct::{path.stem}",
                run_id=run_id,
                family=family,
                source_kind="agent1_direct_task",
                user_intent=user_intent,
                candidate_task=None,
                critic_feedback=None,
                target_task=target_task,
                provenance={
                    "run_dir": str(run_dir.relative_to(ROOT)),
                    "agent1_path": str(path.relative_to(ROOT)),
                },
            )
        )
    return samples


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an initial fallback-task SFT dataset from SageFuzz run artifacts.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_ROOT / f"fallback_taskspec_sft__{_utc_ts()}",
        help="Output directory for the dataset bundle.",
    )
    parser.add_argument(
        "--families",
        nargs="*",
        default=["telemetry_monitoring", "threshold_state_accumulation", "load_distribution_congestion_feedback"],
        help="Only keep samples from these inferred families.",
    )
    args = parser.parse_args()

    all_fallback: List[DatasetSample] = []
    all_review_accept: List[DatasetSample] = []
    all_direct: List[DatasetSample] = []

    for run_dir in sorted(RUNS_DIR.glob("*")):
        if not run_dir.is_dir():
            continue
        all_fallback.extend(_collect_fallback_samples(run_dir))
        all_review_accept.extend(_collect_review_accept_samples(run_dir))
        all_direct.extend(_collect_direct_task_samples(run_dir))

    families = set(args.families)
    fallback_records = [s.to_record() for s in all_fallback if s.family in families]
    review_accept_records = [s.to_record() for s in all_review_accept if s.family in families]
    direct_records = [s.to_record() for s in all_direct if s.family in families]
    mixed_records = fallback_records + review_accept_records + direct_records

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "fallback_only.jsonl", fallback_records)
    _write_jsonl(out_dir / "fallback_review_accept.jsonl", review_accept_records)
    _write_jsonl(out_dir / "direct_only.jsonl", direct_records)
    _write_jsonl(out_dir / "mixed.jsonl", mixed_records)

    summary = {
        "created_at_utc": _utc_ts(),
        "families": sorted(families),
        "counts": {
            "fallback_only": len(fallback_records),
            "fallback_review_accept": len(review_accept_records),
            "direct_only": len(direct_records),
            "mixed": len(mixed_records),
        },
        "family_breakdown": {},
    }
    for family in sorted(families):
        summary["family_breakdown"][family] = {
            "fallback_only": sum(1 for item in fallback_records if item["family"] == family),
            "fallback_review_accept": sum(1 for item in review_accept_records if item["family"] == family),
            "direct_only": sum(1 for item in direct_records if item["family"] == family),
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = [
        "# Fallback TaskSpec SFT Dataset",
        "",
        "Files:",
        "- `fallback_only.jsonl`: samples where the system explicitly switched to task fallback.",
        "- `fallback_review_accept.jsonl`: samples where task review failed to converge and the system accepted a fallback-normalized task.",
        "- `direct_only.jsonl`: direct Agent1 task outputs from the same fallback-relevant families.",
        "- `mixed.jsonl`: union of the two sets.",
        "",
        "Record fields:",
        "- `prompt`: input string for SFT-style training",
        "- `completion`: target `TaskSpec` JSON string",
        "- `user_intent`, `candidate_task`, `critic_feedback`: structured fields for custom preprocessing",
        "- `family`: inferred fallback family label",
        "- `source_kind`: whether the sample came from direct Agent1 output or fallback takeover",
        "",
        "Recommended use:",
        "- Train the fallback small model on `fallback_only.jsonl` first.",
        "- Optionally add selected `direct_only.jsonl` samples to improve format stability.",
        "- Keep evaluation on unseen external programs separated from these training samples.",
        "",
        "Counts:",
        f"- fallback_only: {len(fallback_records)}",
        f"- fallback_review_accept: {len(review_accept_records)}",
        f"- direct_only: {len(direct_records)}",
        f"- mixed: {len(mixed_records)}",
    ]
    (out_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    print(json.dumps({"out_dir": str(out_dir.relative_to(ROOT)), **summary["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
