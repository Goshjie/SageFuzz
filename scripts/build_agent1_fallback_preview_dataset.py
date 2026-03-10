from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "agent_responses"
OUT_DIR = ROOT / "runs" / "training_datasets" / "agent1_fallback_preview__2026-03-10"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get(path: Path, *keys: str) -> Any:
    cur: Any = _load_json(path)
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _prompt(
    *,
    family: str,
    user_intent: Dict[str, Any],
    candidate_task: Optional[Dict[str, Any]],
    critic_feedback: Optional[str],
    source_kind: str,
) -> str:
    payload = {
        "task": "Repair or complete a TaskSpec for an Agent1 fallback model.",
        "family": family,
        "source_kind": source_kind,
        "user_intent": user_intent,
        "candidate_task": candidate_task,
        "critic_feedback": critic_feedback,
        "output_requirement": "Return only the corrected TaskSpec JSON.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class Sample:
    sample_id: str
    family: str
    source_kind: str
    user_intent: Dict[str, Any]
    candidate_task: Optional[Dict[str, Any]]
    critic_feedback: Optional[str]
    target_task: Dict[str, Any]
    provenance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "family": self.family,
            "source_kind": self.source_kind,
            "user_intent": self.user_intent,
            "candidate_task": self.candidate_task,
            "critic_feedback": self.critic_feedback,
            "target_task": self.target_task,
            "prompt": _prompt(
                family=self.family,
                user_intent=self.user_intent,
                candidate_task=self.candidate_task,
                critic_feedback=self.critic_feedback,
                source_kind=self.source_kind,
            ),
            "completion": json.dumps(self.target_task, ensure_ascii=False, indent=2),
            "provenance": self.provenance,
        }


def build_samples() -> List[Sample]:
    samples: List[Sample] = []

    # 1. Telemetry repair sample: bad Agent1 task -> fallback-normalized task.
    run = RUNS / "2026-03-10T121727612511Z"
    user_intent = _get(run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json", "output", "user_intent")
    candidate_task = _get(run / "agent1_semantic_analyzer" / "agent1_output_01.json", "output", "task")
    target_task = _get(run / "deterministic_validator" / "task_contract_review_fallback_accept_05.json", "input", "task")
    critic_feedback = _get(run / "deterministic_validator" / "task_contract_review_fallback_accept_05.json", "output", "feedback")
    samples.append(
        Sample(
            sample_id="telemetry_repair_001",
            family="telemetry_monitoring",
            source_kind="repair_from_feedback",
            user_intent=user_intent,
            candidate_task=candidate_task,
            critic_feedback=critic_feedback,
            target_task=target_task,
            provenance={
                "run_id": run.name,
                "intent_path": str((run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json").relative_to(ROOT)),
                "candidate_task_path": str((run / "agent1_semantic_analyzer" / "agent1_output_01.json").relative_to(ROOT)),
                "target_task_path": str((run / "deterministic_validator" / "task_contract_review_fallback_accept_05.json").relative_to(ROOT)),
            },
        )
    )

    # 2. Telemetry fallback sample: raw intent -> synthesized fallback task.
    run = RUNS / "2026-03-10T130250088490Z"
    user_intent = _get(run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json", "output", "user_intent")
    target_task = _get(run / "deterministic_validator" / "task_contract_fallback_from_intent_06.json", "output", "task")
    samples.append(
        Sample(
            sample_id="telemetry_fallback_001",
            family="telemetry_monitoring",
            source_kind="fallback_from_intent",
            user_intent=user_intent,
            candidate_task=None,
            critic_feedback=None,
            target_task=target_task,
            provenance={
                "run_id": run.name,
                "intent_path": str((run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json").relative_to(ROOT)),
                "target_task_path": str((run / "deterministic_validator" / "task_contract_fallback_from_intent_06.json").relative_to(ROOT)),
            },
        )
    )

    # 3. Threshold fallback sample: raw intent -> synthesized fallback task.
    run = RUNS / "2026-03-10T130501358996Z"
    user_intent = _get(run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json", "output", "user_intent")
    target_task = _get(run / "deterministic_validator" / "task_contract_fallback_from_intent_06.json", "output", "task")
    samples.append(
        Sample(
            sample_id="threshold_fallback_001",
            family="threshold_state_accumulation",
            source_kind="fallback_from_intent",
            user_intent=user_intent,
            candidate_task=None,
            critic_feedback=None,
            target_task=target_task,
            provenance={
                "run_id": run.name,
                "intent_path": str((run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json").relative_to(ROOT)),
                "target_task_path": str((run / "deterministic_validator" / "task_contract_fallback_from_intent_06.json").relative_to(ROOT)),
            },
        )
    )

    # 4. Load-distribution direct anchor sample: valid direct Agent1 task for family shape.
    run = RUNS / "2026-03-07T053442Z"
    user_intent = _get(run / "agent1_semantic_analyzer" / "initial_intent_intake_00.json", "output", "user_intent")
    if not isinstance(user_intent, dict):
        user_intent = _get(run / "agent1_semantic_analyzer" / "agent1_output_01.json", "input", "user_intent")
    target_task = _get(run / "agent1_semantic_analyzer" / "agent1_output_01.json", "output", "task")
    samples.append(
        Sample(
            sample_id="load_distribution_anchor_001",
            family="load_distribution_congestion_feedback",
            source_kind="direct_anchor",
            user_intent=user_intent,
            candidate_task=None,
            critic_feedback=None,
            target_task=target_task,
            provenance={
                "run_id": run.name,
                "agent1_path": str((run / "agent1_semantic_analyzer" / "agent1_output_01.json").relative_to(ROOT)),
            },
        )
    )

    return samples


def main() -> int:
    samples = build_samples()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pretty = [sample.to_dict() for sample in samples]
    (OUT_DIR / "preview.pretty.json").write_text(
        json.dumps(pretty, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT_DIR / "preview.jsonl").open("w", encoding="utf-8") as f:
        for item in pretty:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    lines = [
        "# Agent1 Fallback Preview Dataset",
        "",
        "This preview set is intentionally small and human-readable.",
        "It is meant to show what a fallback-model training sample looks like before large-scale dataset construction.",
        "",
        "Contained sample types:",
        "- `repair_from_feedback`: main Agent1 produced an unstable/incomplete task, later normalized by fallback.",
        "- `fallback_from_intent`: the system directly synthesized a fallback TaskSpec from the original intent.",
        "- `direct_anchor`: a high-quality direct Agent1 task from a fallback-relevant family, useful as a format anchor.",
        "",
        "Files:",
        "- `preview.pretty.json`: easy-to-read pretty JSON",
        "- `preview.jsonl`: line-delimited JSON records for quick downstream processing",
        "",
        f"Sample count: {len(samples)}",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(OUT_DIR.relative_to(ROOT)), "samples": len(samples)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
