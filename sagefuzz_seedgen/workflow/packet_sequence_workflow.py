from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sagefuzz_seedgen.agents.team_factory import build_agents_and_team
from sagefuzz_seedgen.config import RunConfig
from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    AttemptResult,
    Agent1Output,
    CriticResult,
    PacketSequenceCandidate,
    TaskSpec,
    TestcaseOutput,
    TopologySummary,
    UserIntent,
)
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.topology.topology_loader import summarize_topology
from sagefuzz_seedgen.workflow.validation import validate_directional_tcp_state_trigger
from sagefuzz_seedgen.workflow.recorder import AgentRecorder


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _load_json_file(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def _write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def run_packet_sequence_generation(cfg: RunConfig) -> Path:
    run_id = _utc_ts()
    recorder = AgentRecorder(base_dir=Path("runs"), run_id=run_id)

    ctx = initialize_program_context(
        bmv2_json_path=cfg.program.bmv2_json,
        graphs_dir=cfg.program.graphs_dir,
        p4info_path=cfg.program.p4info_txtpb,
        topology_path=cfg.program.topology_json,
    )
    set_program_context(ctx)

    session_state_path = cfg.session_state_path or Path("runs/session_state.json")
    session_state = _load_json_file(session_state_path)
    session_state.setdefault("run_config", {})
    session_state["run_config"].update(
        {
            "max_retries": cfg.max_retries,
            "bmv2_json": str(cfg.program.bmv2_json),
            "graphs_dir": str(cfg.program.graphs_dir),
            "p4info": str(cfg.program.p4info_txtpb),
            "topology": str(cfg.program.topology_json),
        }
    )

    if cfg.model is None:
        raise ValueError("ModelConfig is required to run agents.")

    agent1, agent2, agent3, team = build_agents_and_team(model_cfg=cfg.model, prompts_dir=Path("prompts"))

    # --- Step 1: Collect user intent (intent-driven system) ---
    intent_data = cfg.user_intent or {}
    try:
        user_intent = UserIntent.model_validate(intent_data) if intent_data else None
    except Exception:
        # If the config intent is malformed, treat it as missing so Agent1 can ask questions.
        user_intent = None

    # --- Step 2: Semantic analyzer produces a task spec, or asks user questions ---
    # If intent is missing, Agent1 MUST ask user; we will prompt in terminal and then re-run Agent1.
    max_intent_rounds = 3
    task: TaskSpec | None = None
    for _round in range(1, max_intent_rounds + 1):
        a1_in = {
            "user_intent": user_intent.model_dump() if user_intent else None,
            "note": "If user_intent is missing required fields, return questions instead of guessing.",
        }
        a1_in_str = (
            "You are Agent1. Here is the user_intent JSON (may be null). "
            "If missing required information, ask questions.\n\n"
            + json.dumps(a1_in, indent=2)
        )
        a1_out: Agent1Output = agent1.run(
            a1_in_str,
            output_schema=Agent1Output,
            session_state=session_state,
        ).content  # type: ignore[assignment]
        recorder.record(
            agent_role="agent1_semantic_analyzer",
            step="agent1_output",
            round_id=_round,
            model_input=a1_in,
            model_output=a1_out.model_dump(),
        )

        if a1_out.kind == "task" and a1_out.task is not None:
            task = a1_out.task
            break

        # Ask user and build a UserIntent object
        qs = a1_out.questions or []
        print("\n[Agent1 needs more intent input]")
        if not qs:
            # Safety fallback if the model returned no structured questions.
            print("1. 请补充本次测试的意图信息：要测试的功能点、意图/策略描述、拓扑/安全域划分、internal_host、external_host、是否包含外部主动发起的负例。")
            qs = [
                # Best-effort fields to collect:
                # Note: we keep this minimal; Agent1 should normally provide structured questions.
                {"field": "feature_under_test", "question_zh": "请输入 feature_under_test（要测试的功能点）:", "required": True},
                {"field": "intent_text", "question_zh": "请输入 intent_text（意图/策略描述）:", "required": True},
                {"field": "topology_zone_mapping", "question_zh": "请描述拓扑/安全域划分（例如：h1,h2 属于 internal；h3,h4 属于 external）:", "required": True},
                {"field": "internal_host", "question_zh": "请输入 internal_host（例如 h1）:", "required": True},
                {"field": "external_host", "question_zh": "请输入 external_host（例如 h3）:", "required": True},
                {"field": "include_negative_external_initiation", "question_zh": "是否包含外部主动发起的负例？[y/N]:", "required": False},
            ]

        answers: Dict[str, Any] = {}
        for i, q in enumerate(qs, 1):
            # q may be a UserQuestion or a dict fallback.
            if hasattr(q, "field"):
                field = q.field  # type: ignore[attr-defined]
                qtext = q.question_zh  # type: ignore[attr-defined]
            else:
                field = q.get("field")
                qtext = q.get("question_zh")
            if not isinstance(field, str) or not isinstance(qtext, str):
                continue
            ans = input(f"{i}. {qtext} ").strip()
            if ans == "":
                continue
            if field == "include_negative_external_initiation":
                answers[field] = ans.lower() in ("y", "yes", "true", "1", "是", "对")
            else:
                answers[field] = ans

        # Merge answers into existing intent (if any)
        merged: Dict[str, Any] = {}
        if user_intent is not None:
            merged.update(user_intent.model_dump())
        merged.update(answers)

        try:
            user_intent = UserIntent.model_validate(merged)
        except Exception:
            user_intent = None
            print("Invalid intent input; please try again.\n")

    if task is None:
        raise RuntimeError("Unable to obtain sufficient user intent to generate a task.")

    # Ensure defaults are present for this program if agent returns empty/unknown.
    if not task.internal_host:
        task.internal_host = cfg.default_internal_host  # type: ignore[misc]
    if not task.external_host:
        task.external_host = cfg.default_external_host  # type: ignore[misc]

    last_feedback: Optional[str] = None
    last_attempt: Optional[AttemptResult] = None
    attempt_count: int = 0

    # --- Step 3: Generate packet_sequence with critic loop ---
    for attempt in range(1, cfg.max_retries + 1):
        attempt_count = attempt
        gen_in = {
            "attempt": attempt,
            "task": task.model_dump(),
            "user_intent": user_intent.model_dump() if user_intent else None,
            "previous_feedback": last_feedback,
        }
        gen_in_str = (
            "Generate PacketSequenceCandidate STRICT JSON. Input:\n\n" + json.dumps(gen_in, indent=2)
        )
        cand_out = agent2.run(
            gen_in_str,
            output_schema=PacketSequenceCandidate,
            session_state=session_state,
        )
        candidate: PacketSequenceCandidate = cand_out.content  # type: ignore[assignment]
        recorder.record(
            agent_role="agent2_sequence_constructor",
            step="packet_sequence_candidate",
            round_id=attempt,
            model_input=gen_in,
            model_output=candidate.model_dump(),
        )

        critic_in = {
            "task": task.model_dump(),
            "user_intent": user_intent.model_dump() if user_intent else None,
            "packet_sequence_candidate": candidate.model_dump(),
        }
        critic_in_str = "Evaluate candidate and return CriticResult STRICT JSON:\n\n" + json.dumps(critic_in, indent=2)
        critic_out = agent3.run(
            critic_in_str,
            output_schema=CriticResult,
            session_state=session_state,
        )
        llm_critic: CriticResult = critic_out.content  # type: ignore[assignment]
        recorder.record(
            agent_role="agent3_constraint_critic",
            step="critic_result",
            round_id=attempt,
            model_input=critic_in,
            model_output=llm_critic.model_dump(),
        )

        attempt_result = AttemptResult(task_id=task.task_id, packet_sequence=candidate.packet_sequence, critic=llm_critic)

        # Always run deterministic validator as the ground truth for this stage's DoD.
        det = validate_directional_tcp_state_trigger(ctx=ctx, task=task, packet_sequence=attempt_result.packet_sequence)
        if det.status == "FAIL":
            attempt_result.critic = det
        recorder.record(
            agent_role="deterministic_validator",
            step="deterministic_validation",
            round_id=attempt,
            model_input={"task": task.model_dump(), "packet_sequence": [p.model_dump() for p in attempt_result.packet_sequence]},
            model_output=attempt_result.critic.model_dump(),
        )

        last_attempt = attempt_result
        last_feedback = attempt_result.critic.feedback

        if attempt_result.critic.status == "PASS":
            break

    if last_attempt is None:
        raise RuntimeError("No attempt was executed.")

    topo = summarize_topology(ctx.topology)
    topo_summary = TopologySummary(hosts=topo["hosts"], links=topo["links"])

    output = TestcaseOutput(
        program=ctx.program_name or "unknown",
        topology_ref=str(ctx.topology_path),
        topology=topo_summary,
        task_id=task.task_id,
        packet_sequence=last_attempt.packet_sequence,
        meta={
            "generator": "sagefuzz_seedgen",
            "timestamp_utc": _utc_ts(),
            "attempts": attempt_count,
            "final_status": last_attempt.critic.status,
            "final_feedback": last_attempt.critic.feedback,
        },
    )

    out_path = cfg.out_path or Path("runs") / f"{_utc_ts()}_packet_sequence.json"
    _write_json_file(out_path, output.model_dump())
    _write_json_file(session_state_path, session_state)

    return out_path
