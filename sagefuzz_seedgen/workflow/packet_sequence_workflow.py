from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel

from sagefuzz_seedgen.agents.team_factory import build_agents_and_team
from sagefuzz_seedgen.config import RunConfig
from sagefuzz_seedgen.runtime.agno_patches import install_agno_argument_patch
from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    AttemptResult,
    Agent1Output,
    CriticResult,
    PacketSequenceCandidate,
    RuleSetCandidate,
    TaskSpec,
    TestcaseOutput,
    TopologySummary,
    UserIntent,
)
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.topology.topology_loader import summarize_topology
from sagefuzz_seedgen.workflow.validation import (
    validate_control_plane_entities,
    validate_directional_tcp_state_trigger,
)
from sagefuzz_seedgen.workflow.recorder import AgentRecorder


SchemaT = TypeVar("SchemaT", bound=BaseModel)


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


def _to_recordable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    return str(value)


def _coerce_schema_output(raw_content: Any, schema: Type[SchemaT]) -> Optional[SchemaT]:
    if isinstance(raw_content, schema):
        return raw_content

    candidate: Any = raw_content
    if isinstance(raw_content, str):
        text = raw_content.strip()
        if not text:
            return None
        try:
            candidate = json.loads(text)
        except Exception:
            # Best effort: try to parse the first JSON object in a mixed string.
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    candidate = json.loads(text[start : end + 1])
                except Exception:
                    return None
            else:
                return None

    try:
        return schema.model_validate(candidate)
    except Exception:
        return None


def _error_text(err: Exception) -> str:
    msg = str(err).strip()
    return msg or err.__class__.__name__


def _as_non_empty_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _prompt_with_default(question: str, default_value: Optional[str]) -> str:
    try:
        if default_value:
            answer = input(f"{question} [默认: {default_value}] ").strip()
            return answer or default_value
        return input(f"{question} ").strip()
    except EOFError:
        # Non-interactive mode: keep existing defaults when stdin is unavailable.
        return default_value or ""


def _apply_fixed_intake_answers(
    *,
    intent_payload: Dict[str, Any],
    test_intent: str,
    topology_description: str,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(intent_payload)
    if test_intent:
        # The first fixed question is the user's core test intent; keep both fields aligned by default.
        merged["intent_text"] = test_intent
        merged["feature_under_test"] = test_intent
    if topology_description:
        merged["topology_zone_mapping"] = topology_description
    return merged


def _collect_fixed_intake(intent_payload: Dict[str, Any]) -> Dict[str, Any]:
    print("\n[初始化输入] 请先回答两个固定问题：")
    default_intent = _as_non_empty_str(intent_payload.get("intent_text")) or _as_non_empty_str(
        intent_payload.get("feature_under_test")
    )
    default_topology = _as_non_empty_str(intent_payload.get("topology_zone_mapping"))

    test_intent = _prompt_with_default(
        "1. 请输入测试意图（要测试的功能/策略）:",
        default_intent,
    )
    topology_description = _prompt_with_default(
        "2. 请简要描述拓扑结构与安全域角色划分:",
        default_topology,
    )
    return _apply_fixed_intake_answers(
        intent_payload=intent_payload,
        test_intent=test_intent,
        topology_description=topology_description,
    )


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

    install_agno_argument_patch()
    agent1, agent2, agent3, agent4, agent5, _team = build_agents_and_team(
        model_cfg=cfg.model,
        prompts_dir=Path("prompts"),
    )
    # Agent1 receives its system prompt at construction time. Then we collect fixed user inputs.

    # --- Step 1: Collect fixed initial intent (two mandatory bootstrap questions) ---
    intent_payload: Dict[str, Any] = dict(cfg.user_intent) if isinstance(cfg.user_intent, dict) else {}
    intent_payload = _collect_fixed_intake(intent_payload)
    recorder.record(
        agent_role="agent1_semantic_analyzer",
        step="fixed_intent_bootstrap",
        round_id=0,
        model_input={"source": "fixed_questions"},
        model_output={"user_intent": intent_payload or None},
    )

    # --- Step 2: Semantic analyzer produces a task spec, or asks model-driven follow-up questions ---
    max_intent_rounds = 3
    task: TaskSpec | None = None
    for _round in range(1, max_intent_rounds + 1):
        a1_in = {
            "user_intent": intent_payload or None,
            "note": "If user_intent is missing required fields, return questions instead of guessing.",
        }
        a1_in_str = (
            "You are Agent1. Here is the user_intent JSON (may be null). "
            "If missing required information, ask questions.\n\n"
            + json.dumps(a1_in, indent=2)
        )
        a1_raw = agent1.run(
            a1_in_str,
            output_schema=Agent1Output,
            session_state=session_state,
        ).content
        a1_out = _coerce_schema_output(a1_raw, Agent1Output)
        if a1_out is None:
            # Safety: do not crash when provider emits malformed schema output.
            print("\n[WARN] Agent1 输出解析失败，切换到兜底问题收集。")
            a1_out = Agent1Output(kind="questions", questions=[])
        recorder.record(
            agent_role="agent1_semantic_analyzer",
            step="agent1_output",
            round_id=_round,
            model_input=a1_in,
            model_output=_to_recordable(a1_out),
            extra={"raw_output": _to_recordable(a1_raw)},
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
        intent_payload.update(answers)

    if task is None:
        raise RuntimeError("Unable to obtain sufficient user intent to generate a task.")

    try:
        user_intent = UserIntent.model_validate(intent_payload) if intent_payload else None
    except Exception:
        user_intent = None
    user_intent_payload = user_intent.model_dump() if user_intent else (intent_payload or None)

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
            "user_intent": user_intent_payload,
            "previous_feedback": last_feedback,
        }
        gen_in_str = (
            "Generate PacketSequenceCandidate STRICT JSON. Input:\n\n" + json.dumps(gen_in, indent=2)
        )
        try:
            cand_raw = agent2.run(
                gen_in_str,
                output_schema=PacketSequenceCandidate,
                session_state=session_state,
            ).content
        except Exception as e:
            last_feedback = f"Agent2 API error: {_error_text(e)}"
            recorder.record(
                agent_role="agent2_sequence_constructor",
                step="packet_sequence_candidate",
                round_id=attempt,
                model_input=gen_in,
                model_output={"error": "agent_run_exception", "message": _error_text(e)},
            )
            continue
        candidate = _coerce_schema_output(cand_raw, PacketSequenceCandidate)
        if candidate is None:
            last_feedback = "Agent2 schema parse failed (possibly timeout/non-JSON output)."
            recorder.record(
                agent_role="agent2_sequence_constructor",
                step="packet_sequence_candidate",
                round_id=attempt,
                model_input=gen_in,
                model_output={"error": "schema_parse_failed"},
                extra={"raw_output": _to_recordable(cand_raw)},
            )
            continue
        recorder.record(
            agent_role="agent2_sequence_constructor",
            step="packet_sequence_candidate",
            round_id=attempt,
            model_input=gen_in,
            model_output=candidate.model_dump(),
        )

        critic_in = {
            "task": task.model_dump(),
            "user_intent": user_intent_payload,
            "packet_sequence_candidate": candidate.model_dump(),
        }
        critic_in_str = "Evaluate candidate and return CriticResult STRICT JSON:\n\n" + json.dumps(critic_in, indent=2)
        try:
            critic_raw = agent3.run(
                critic_in_str,
                output_schema=CriticResult,
                session_state=session_state,
            ).content
        except Exception as e:
            last_feedback = f"Agent3 API error: {_error_text(e)}"
            recorder.record(
                agent_role="agent3_constraint_critic",
                step="critic_result",
                round_id=attempt,
                model_input=critic_in,
                model_output={"error": "agent_run_exception", "message": _error_text(e)},
            )
            continue
        llm_critic = _coerce_schema_output(critic_raw, CriticResult)
        if llm_critic is None:
            last_feedback = "Agent3 schema parse failed (possibly timeout/non-JSON output)."
            recorder.record(
                agent_role="agent3_constraint_critic",
                step="critic_result",
                round_id=attempt,
                model_input=critic_in,
                model_output={"error": "schema_parse_failed"},
                extra={"raw_output": _to_recordable(critic_raw)},
            )
            continue
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
        raise RuntimeError(
            f"No packet_sequence attempt succeeded after {cfg.max_retries} retries. Last feedback: {last_feedback}"
        )

    # --- Step 4: Generate control-plane entities (rules) with critic loop ---
    last_entity_feedback: Optional[str] = None
    last_entities: Optional[RuleSetCandidate] = None
    last_entity_critic: Optional[CriticResult] = None
    entity_attempt_count = 0

    for attempt in range(1, cfg.max_retries + 1):
        entity_attempt_count = attempt
        entity_gen_in = {
            "attempt": attempt,
            "task": task.model_dump(),
            "user_intent": user_intent_payload,
            "packet_sequence": [p.model_dump() for p in last_attempt.packet_sequence],
            "previous_feedback": last_entity_feedback,
        }
        entity_gen_in_str = "Generate RuleSetCandidate STRICT JSON. Input:\n\n" + json.dumps(entity_gen_in, indent=2)
        try:
            entity_raw = agent4.run(
                entity_gen_in_str,
                output_schema=RuleSetCandidate,
                session_state=session_state,
            ).content
        except Exception as e:
            last_entity_feedback = f"Agent4 API error: {_error_text(e)}"
            recorder.record(
                agent_role="agent4_entity_generator",
                step="entity_candidate",
                round_id=attempt,
                model_input=entity_gen_in,
                model_output={"error": "agent_run_exception", "message": _error_text(e)},
            )
            continue
        entity_candidate = _coerce_schema_output(entity_raw, RuleSetCandidate)
        if entity_candidate is None:
            last_entity_feedback = "Agent4 schema parse failed (possibly timeout/non-JSON output)."
            recorder.record(
                agent_role="agent4_entity_generator",
                step="entity_candidate",
                round_id=attempt,
                model_input=entity_gen_in,
                model_output={"error": "schema_parse_failed"},
                extra={"raw_output": _to_recordable(entity_raw)},
            )
            continue
        recorder.record(
            agent_role="agent4_entity_generator",
            step="entity_candidate",
            round_id=attempt,
            model_input=entity_gen_in,
            model_output=entity_candidate.model_dump(),
        )

        entity_critic_in = {
            "task": task.model_dump(),
            "user_intent": user_intent_payload,
            "packet_sequence": [p.model_dump() for p in last_attempt.packet_sequence],
            "rule_set_candidate": entity_candidate.model_dump(),
        }
        entity_critic_in_str = (
            "Evaluate control-plane entities and return CriticResult STRICT JSON:\n\n"
            + json.dumps(entity_critic_in, indent=2)
        )
        try:
            entity_critic_raw = agent5.run(
                entity_critic_in_str,
                output_schema=CriticResult,
                session_state=session_state,
            ).content
        except Exception as e:
            last_entity_feedback = f"Agent5 API error: {_error_text(e)}"
            recorder.record(
                agent_role="agent5_entity_critic",
                step="entity_critic_result",
                round_id=attempt,
                model_input=entity_critic_in,
                model_output={"error": "agent_run_exception", "message": _error_text(e)},
            )
            continue
        llm_entity_critic = _coerce_schema_output(entity_critic_raw, CriticResult)
        if llm_entity_critic is None:
            last_entity_feedback = "Agent5 schema parse failed (possibly timeout/non-JSON output)."
            recorder.record(
                agent_role="agent5_entity_critic",
                step="entity_critic_result",
                round_id=attempt,
                model_input=entity_critic_in,
                model_output={"error": "schema_parse_failed"},
                extra={"raw_output": _to_recordable(entity_critic_raw)},
            )
            continue
        recorder.record(
            agent_role="agent5_entity_critic",
            step="entity_critic_result",
            round_id=attempt,
            model_input=entity_critic_in,
            model_output=llm_entity_critic.model_dump(),
        )

        det_entity_critic = validate_control_plane_entities(
            ctx=ctx,
            task=task,
            packet_sequence=last_attempt.packet_sequence,
            entities=entity_candidate.entities,
        )
        recorder.record(
            agent_role="deterministic_validator",
            step="deterministic_entity_validation",
            round_id=attempt,
            model_input={
                "task": task.model_dump(),
                "packet_sequence": [p.model_dump() for p in last_attempt.packet_sequence],
                "entities": [e.model_dump() for e in entity_candidate.entities],
            },
            model_output=det_entity_critic.model_dump(),
        )

        # For this stage, deterministic validation is the final gate.
        final_entity_critic = det_entity_critic if det_entity_critic.status == "FAIL" else llm_entity_critic
        last_entities = entity_candidate
        last_entity_critic = final_entity_critic
        last_entity_feedback = final_entity_critic.feedback

        if final_entity_critic.status == "PASS":
            break

    if last_entities is None or last_entity_critic is None:
        raise RuntimeError(
            f"No entity generation attempt succeeded after {cfg.max_retries} retries. Last feedback: {last_entity_feedback}"
        )

    topo = summarize_topology(ctx.topology)
    topo_summary = TopologySummary(hosts=topo["hosts"], links=topo["links"])

    final_status = "PASS" if (last_attempt.critic.status == "PASS" and last_entity_critic.status == "PASS") else "FAIL"
    final_feedback = (
        f"packet_sequence: {last_attempt.critic.status} ({last_attempt.critic.feedback}); "
        f"entities: {last_entity_critic.status} ({last_entity_critic.feedback})"
    )

    output = TestcaseOutput(
        program=ctx.program_name or "unknown",
        topology_ref=str(ctx.topology_path),
        topology=topo_summary,
        task_id=task.task_id,
        packet_sequence=last_attempt.packet_sequence,
        entities=last_entities.entities,
        meta={
            "generator": "sagefuzz_seedgen",
            "timestamp_utc": _utc_ts(),
            "attempts_packet_sequence": attempt_count,
            "attempts_entities": entity_attempt_count,
            "packet_sequence_status": last_attempt.critic.status,
            "packet_sequence_feedback": last_attempt.critic.feedback,
            "entities_status": last_entity_critic.status,
            "entities_feedback": last_entity_critic.feedback,
            "final_status": final_status,
            "final_feedback": final_feedback,
        },
    )

    out_path = cfg.out_path or Path("runs") / f"{_utc_ts()}_packet_sequence.json"
    _write_json_file(out_path, output.model_dump())
    _write_json_file(session_state_path, session_state)

    return out_path
