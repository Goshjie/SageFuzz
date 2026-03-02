from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel

from sagefuzz_seedgen.agents.team_factory import build_agents_and_team
from sagefuzz_seedgen.config import RunConfig
from sagefuzz_seedgen.runtime.agno_patches import install_agno_argument_patch
from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    AttemptResult,
    Agent1Output,
    ControlPlaneOperation,
    CriticResult,
    ExecutionOperation,
    OraclePacketPrediction,
    OraclePredictionCandidate,
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
    validate_execution_sequence,
    validate_packet_sequence_contract,
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


def _parse_role_bindings_answer(value: str) -> Optional[Dict[str, str]]:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    out: Dict[str, str] = {}
    for key, host in parsed.items():
        if isinstance(key, str) and isinstance(host, str) and key.strip() and host.strip():
            out[key.strip()] = host.strip()
    return out or None


def _scenario_name(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    return text or "default"


def _scenario_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return slug or "default"


def _group_packets_by_scenario(packet_sequence: List[Any]) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {}
    for packet in packet_sequence:
        scenario = _scenario_name(getattr(packet, "scenario", None))
        out.setdefault(scenario, []).append(packet)
    return out


def _normalize_control_plane_sequence(candidate: RuleSetCandidate) -> List[ControlPlaneOperation]:
    """Ensure testcase always contains explicit ordered control-plane operations."""
    if candidate.control_plane_sequence:
        normalized: List[ControlPlaneOperation] = []
        for idx, op in enumerate(candidate.control_plane_sequence, 1):
            # Keep user-provided semantic order while enforcing canonical increasing order.
            normalized.append(op.model_copy(update={"order": idx}))
        return normalized

    # Fallback: derive one apply operation per generated entity in order.
    derived: List[ControlPlaneOperation] = []
    for idx, rule in enumerate(candidate.entities, 1):
        derived.append(
            ControlPlaneOperation(
                order=idx,
                operation_type="apply_table_entry",
                target=rule.table_name,
                entity_index=idx,
                parameters={
                    "match_type": rule.match_type,
                    "action_name": rule.action_name,
                },
                expected_effect=f"entity[{idx}] applied",
            )
        )
    return derived


def _normalize_execution_sequence(
    *,
    candidate: RuleSetCandidate,
    packet_sequence: List[Any],
    control_plane_sequence: List[ControlPlaneOperation],
) -> List[ExecutionOperation]:
    """Ensure testcase has one unified execution timeline."""
    if candidate.execution_sequence:
        normalized: List[ExecutionOperation] = []
        for idx, step in enumerate(candidate.execution_sequence, 1):
            normalized.append(step.model_copy(update={"order": idx}))
        return normalized

    derived: List[ExecutionOperation] = []
    order = 1
    for op in control_plane_sequence:
        derived.append(
            ExecutionOperation(
                order=order,
                operation_type=op.operation_type,
                entity_index=op.entity_index,
                control_plane_order=op.order,
                target=op.target,
                parameters=op.parameters,
                expected_effect=op.expected_effect,
            )
        )
        order += 1

    for packet in packet_sequence:
        derived.append(
            ExecutionOperation(
                order=order,
                operation_type="send_packet",
                packet_id=int(getattr(packet, "packet_id")),
                target=str(getattr(packet, "tx_host", "")),
                parameters={"scenario": _scenario_name(getattr(packet, "scenario", None))},
                expected_effect=f"packet {getattr(packet, 'packet_id', '?')} sent",
            )
        )
        order += 1

    return derived


def _resolve_output_paths(run_id: str, out_path: Optional[Path]) -> Tuple[Path, Path]:
    if out_path is None:
        return (
            Path("runs") / f"{run_id}_packet_sequence_index.json",
            Path("runs") / f"{run_id}_testcases",
        )
    if out_path.suffix:
        return (out_path, out_path.parent / f"{out_path.stem}_cases")
    return (out_path / "index.json", out_path)


def _split_case_records_by_kind(case_records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out = {"positive": [], "negative": [], "neutral": []}
    for item in case_records:
        kind = str(item.get("kind") or "neutral").lower()
        if kind not in out:
            kind = "neutral"
        out[kind].append(item)
    return out


def _validate_oracle_prediction_candidate(
    *,
    task_id: str,
    scenario: str,
    packet_sequence: List[Any],
    prediction: OraclePredictionCandidate,
) -> Optional[str]:
    if prediction.task_id != task_id:
        return f"task_id mismatch: expected '{task_id}', got '{prediction.task_id}'."
    if prediction.scenario != scenario:
        return f"scenario mismatch: expected '{scenario}', got '{prediction.scenario}'."

    expected_ids = [int(getattr(packet, "packet_id")) for packet in packet_sequence]
    pred_ids = [int(item.packet_id) for item in prediction.packet_predictions]
    if len(set(pred_ids)) != len(pred_ids):
        return "packet_predictions contains duplicate packet_id."

    missing = [packet_id for packet_id in expected_ids if packet_id not in set(pred_ids)]
    extra = [packet_id for packet_id in pred_ids if packet_id not in set(expected_ids)]
    if missing:
        return f"packet_predictions missing packet_id(s): {missing}."
    if extra:
        return f"packet_predictions has unknown packet_id(s): {extra}."
    return None


def _fallback_oracle_prediction(
    *,
    task_id: str,
    scenario: str,
    packet_sequence: List[Any],
    reason: str,
) -> OraclePredictionCandidate:
    predictions = [
        OraclePacketPrediction(
            packet_id=int(getattr(packet, "packet_id")),
            expected_outcome="unknown",
            expected_observation="fallback_unknown",
            rationale=reason,
        )
        for packet in packet_sequence
    ]
    return OraclePredictionCandidate(
        task_id=task_id,
        scenario=scenario,
        packet_predictions=predictions,
        assumptions=[
            "fallback_from_orchestrator",
            "prediction generated in fallback mode due to model output issues.",
        ],
    )


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
    agent1, agent2, agent3, agent4, agent5, agent6, _team = build_agents_and_team(
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
    agent1_feedback: Optional[str] = None
    for _round in range(1, max_intent_rounds + 1):
        a1_in = {
            "user_intent": intent_payload or None,
            "previous_feedback": agent1_feedback,
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
            # Agent-based semantic completeness check for TaskSpec before Agent2 generation.
            task_review_in = {
                "mode": "task_contract_review",
                "task": a1_out.task.model_dump(),
                "user_intent": intent_payload or None,
                "review_hint": (
                    "Check whether sequence_contract semantically matches user intent. "
                    "For stateful/directional intents, positive scenario should be a full ordered transaction "
                    "(not collapsed to one packet)."
                ),
            }
            task_review_in_str = (
                "Review TaskSpec semantic completeness and return CriticResult STRICT JSON:\n\n"
                + json.dumps(task_review_in, indent=2)
            )
            try:
                task_review_raw = agent3.run(
                    task_review_in_str,
                    output_schema=CriticResult,
                    session_state=session_state,
                ).content
            except Exception as e:
                # Avoid blocking generation on review API failures.
                recorder.record(
                    agent_role="agent3_constraint_critic",
                    step="task_contract_review",
                    round_id=_round,
                    model_input=task_review_in,
                    model_output={"error": "agent_run_exception", "message": _error_text(e)},
                )
                task = a1_out.task
                break

            task_review = _coerce_schema_output(task_review_raw, CriticResult)
            recorder.record(
                agent_role="agent3_constraint_critic",
                step="task_contract_review",
                round_id=_round,
                model_input=task_review_in,
                model_output=_to_recordable(task_review) if task_review is not None else {"error": "schema_parse_failed"},
                extra={"raw_output": _to_recordable(task_review_raw)},
            )
            if task_review is not None and task_review.status == "FAIL":
                print(f"\n[WARN] Agent3 认为 TaskSpec 语义不完整：{task_review.feedback}")
                agent1_feedback = task_review.feedback
                continue

            task = a1_out.task
            break

        # Ask user and build a UserIntent object
        qs = a1_out.questions or []
        print("\n[Agent1 needs more intent input]")
        if not qs:
            # Safety fallback if the model returned no structured questions.
            print("1. 请补充本次测试的意图信息：要测试的功能点、策略描述、角色通信策略、拓扑/安全域划分。")
            qs = [
                # Best-effort fields to collect:
                # Note: we keep this minimal; Agent1 should normally provide structured questions.
                {"field": "feature_under_test", "question_zh": "请输入 feature_under_test（要测试的功能点）:", "required": True},
                {"field": "intent_text", "question_zh": "请输入 intent_text（意图/策略描述）:", "required": True},
                {"field": "topology_zone_mapping", "question_zh": "请描述拓扑/安全域划分（例如：h1,h2 属于 trusted；h3,h4 属于 untrusted）:", "required": True},
                {"field": "role_policy", "question_zh": "请描述通信角色策略（例如 initiator 允许发起，responder 仅回复）:", "required": True},
                {"field": "preferred_role_bindings", "question_zh": "可选：请输入角色到主机的映射 JSON（例如 {\"initiator\":\"h2\",\"responder\":\"h3\"}）:", "required": False},
                {"field": "include_negative_case", "question_zh": "是否包含负例场景？[y/N]:", "required": False},
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
            if field == "include_negative_case":
                answers[field] = ans.lower() in ("y", "yes", "true", "1", "是", "对")
            elif field == "preferred_role_bindings":
                parsed_bindings = _parse_role_bindings_answer(ans)
                answers[field] = parsed_bindings if parsed_bindings is not None else ans
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

    # Ensure role bindings are present if the model omitted them.
    if not task.role_bindings:
        task.role_bindings = {
            "initiator": cfg.default_initiator_host,
            "responder": cfg.default_responder_host,
        }
    if not task.sequence_contract:
        raise RuntimeError("TaskSpec.sequence_contract is empty. Agent1 must define scenario contracts.")

    generation_start_ts = _utc_ts()
    generation_start_mono = time.perf_counter()

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
        det = validate_packet_sequence_contract(ctx=ctx, task=task, packet_sequence=attempt_result.packet_sequence)
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

    # --- Step 4: Generate control-plane entities per scenario ---
    topo = summarize_topology(ctx.topology)
    topo_summary = TopologySummary(hosts=topo["hosts"], links=topo["links"])
    scenario_packets_map = _group_packets_by_scenario(last_attempt.packet_sequence)

    scenario_order: List[str] = []
    scenario_meta: Dict[str, Dict[str, Any]] = {}
    for contract in task.sequence_contract:
        scenario = _scenario_name(contract.scenario)
        if scenario not in scenario_meta:
            scenario_order.append(scenario)
            scenario_meta[scenario] = {"kind": contract.kind, "required": contract.required}
    for scenario in scenario_packets_map.keys():
        if scenario not in scenario_meta:
            scenario_order.append(scenario)
            scenario_meta[scenario] = {"kind": "neutral", "required": False}

    scenario_outputs: Dict[str, TestcaseOutput] = {}
    scenario_entity_status: Dict[str, str] = {}
    scenario_entity_feedback: Dict[str, str] = {}
    scenario_entity_attempts: Dict[str, int] = {}
    scenario_oracle_prediction_status: Dict[str, str] = {}
    scenario_oracle_prediction_feedback: Dict[str, str] = {}
    scenario_oracle_prediction_attempts: Dict[str, int] = {}

    for scenario in scenario_order:
        packets_for_scenario = scenario_packets_map.get(scenario, [])
        if not packets_for_scenario:
            if bool(scenario_meta.get(scenario, {}).get("required")):
                raise RuntimeError(f"Required scenario '{scenario}' has no packets in packet_sequence.")
            continue

        scenario_slug = _scenario_slug(scenario)
        scenario_kind = str(scenario_meta.get(scenario, {}).get("kind") or "neutral")
        last_entity_feedback: Optional[str] = None
        last_entities: Optional[RuleSetCandidate] = None
        last_entity_critic: Optional[CriticResult] = None
        entity_attempt_count = 0

        for attempt in range(1, cfg.max_retries + 1):
            entity_attempt_count = attempt
            entity_gen_in = {
                "attempt": attempt,
                "scenario": scenario,
                "scenario_kind": scenario_kind,
                "task": task.model_dump(),
                "user_intent": user_intent_payload,
                "packet_sequence": [p.model_dump() for p in packets_for_scenario],
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
                    step=f"entity_candidate_{scenario_slug}",
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
                    step=f"entity_candidate_{scenario_slug}",
                    round_id=attempt,
                    model_input=entity_gen_in,
                    model_output={"error": "schema_parse_failed"},
                    extra={"raw_output": _to_recordable(entity_raw)},
                )
                continue
            recorder.record(
                agent_role="agent4_entity_generator",
                step=f"entity_candidate_{scenario_slug}",
                round_id=attempt,
                model_input=entity_gen_in,
                model_output=entity_candidate.model_dump(),
            )
            normalized_cp_sequence = _normalize_control_plane_sequence(entity_candidate)
            normalized_execution_sequence = _normalize_execution_sequence(
                candidate=entity_candidate,
                packet_sequence=packets_for_scenario,
                control_plane_sequence=normalized_cp_sequence,
            )

            entity_critic_in = {
                "scenario": scenario,
                "scenario_kind": scenario_kind,
                "task": task.model_dump(),
                "user_intent": user_intent_payload,
                "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                "rule_set_candidate": {
                    **entity_candidate.model_dump(),
                    "control_plane_sequence": [op.model_dump() for op in normalized_cp_sequence],
                    "execution_sequence": [op.model_dump() for op in normalized_execution_sequence],
                },
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
                    step=f"entity_critic_result_{scenario_slug}",
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
                    step=f"entity_critic_result_{scenario_slug}",
                    round_id=attempt,
                    model_input=entity_critic_in,
                    model_output={"error": "schema_parse_failed"},
                    extra={"raw_output": _to_recordable(entity_critic_raw)},
                )
                continue
            recorder.record(
                agent_role="agent5_entity_critic",
                step=f"entity_critic_result_{scenario_slug}",
                round_id=attempt,
                model_input=entity_critic_in,
                model_output=llm_entity_critic.model_dump(),
            )

            det_entity_critic = validate_control_plane_entities(
                ctx=ctx,
                task=task,
                packet_sequence=packets_for_scenario,
                entities=entity_candidate.entities,
                control_plane_sequence=normalized_cp_sequence,
            )
            det_execution_critic = validate_execution_sequence(
                packet_sequence=packets_for_scenario,
                entities=entity_candidate.entities,
                control_plane_sequence=normalized_cp_sequence,
                execution_sequence=normalized_execution_sequence,
            )
            recorder.record(
                agent_role="deterministic_validator",
                step=f"deterministic_entity_validation_{scenario_slug}",
                round_id=attempt,
                model_input={
                    "scenario": scenario,
                    "task": task.model_dump(),
                    "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                    "entities": [e.model_dump() for e in entity_candidate.entities],
                    "control_plane_sequence": [op.model_dump() for op in normalized_cp_sequence],
                    "execution_sequence": [op.model_dump() for op in normalized_execution_sequence],
                },
                model_output=det_entity_critic.model_dump(),
            )
            recorder.record(
                agent_role="deterministic_validator",
                step=f"deterministic_execution_validation_{scenario_slug}",
                round_id=attempt,
                model_input={
                    "scenario": scenario,
                    "task": task.model_dump(),
                    "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                    "entities": [e.model_dump() for e in entity_candidate.entities],
                    "control_plane_sequence": [op.model_dump() for op in normalized_cp_sequence],
                    "execution_sequence": [op.model_dump() for op in normalized_execution_sequence],
                },
                model_output=det_execution_critic.model_dump(),
            )

            final_entity_critic = llm_entity_critic
            if det_entity_critic.status == "FAIL":
                final_entity_critic = det_entity_critic
            elif det_execution_critic.status == "FAIL":
                final_entity_critic = det_execution_critic
            last_entities = entity_candidate.model_copy(
                update={
                    "control_plane_sequence": normalized_cp_sequence,
                    "execution_sequence": normalized_execution_sequence,
                }
            )
            last_entity_critic = final_entity_critic
            last_entity_feedback = final_entity_critic.feedback

            if final_entity_critic.status == "PASS":
                break

        if last_entities is None or last_entity_critic is None:
            raise RuntimeError(
                f"No entity generation attempt succeeded for scenario '{scenario}' after {cfg.max_retries} retries. "
                f"Last feedback: {last_entity_feedback}"
            )

        scenario_entity_status[scenario] = last_entity_critic.status
        scenario_entity_feedback[scenario] = last_entity_critic.feedback
        scenario_entity_attempts[scenario] = entity_attempt_count

        # --- Step 5: Agent6 oracle prediction (per scenario) ---
        last_oracle_feedback: Optional[str] = None
        oracle_prediction: Optional[OraclePredictionCandidate] = None
        oracle_attempt_count = 0
        for attempt in range(1, cfg.max_retries + 1):
            oracle_attempt_count = attempt
            oracle_in = {
                "attempt": attempt,
                "task": task.model_dump(),
                "scenario": scenario,
                "scenario_kind": scenario_kind,
                "user_intent": user_intent_payload,
                "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                "entities": [e.model_dump() for e in last_entities.entities],
                "control_plane_sequence": [op.model_dump() for op in last_entities.control_plane_sequence],
                "execution_sequence": [op.model_dump() for op in last_entities.execution_sequence],
                "topology": topo_summary.model_dump(),
                "previous_feedback": last_oracle_feedback,
            }
            oracle_in_str = (
                "Generate OraclePredictionCandidate STRICT JSON. Input:\n\n" + json.dumps(oracle_in, indent=2)
            )
            try:
                oracle_raw = agent6.run(
                    oracle_in_str,
                    output_schema=OraclePredictionCandidate,
                    session_state=session_state,
                ).content
            except Exception as e:
                last_oracle_feedback = f"Agent6 API error: {_error_text(e)}"
                recorder.record(
                    agent_role="agent6_oracle_predictor",
                    step=f"oracle_prediction_{scenario_slug}",
                    round_id=attempt,
                    model_input=oracle_in,
                    model_output={"error": "agent_run_exception", "message": _error_text(e)},
                )
                continue
            oracle_candidate = _coerce_schema_output(oracle_raw, OraclePredictionCandidate)
            if oracle_candidate is None:
                last_oracle_feedback = "Agent6 schema parse failed (possibly timeout/non-JSON output)."
                recorder.record(
                    agent_role="agent6_oracle_predictor",
                    step=f"oracle_prediction_{scenario_slug}",
                    round_id=attempt,
                    model_input=oracle_in,
                    model_output={"error": "schema_parse_failed"},
                    extra={"raw_output": _to_recordable(oracle_raw)},
                )
                continue

            validation_feedback = _validate_oracle_prediction_candidate(
                task_id=task.task_id,
                scenario=scenario,
                packet_sequence=packets_for_scenario,
                prediction=oracle_candidate,
            )
            det_oracle_critic = CriticResult(
                status="FAIL" if validation_feedback else "PASS",
                feedback=validation_feedback or "oracle prediction passes deterministic sanity checks.",
            )
            recorder.record(
                agent_role="deterministic_validator",
                step=f"deterministic_oracle_validation_{scenario_slug}",
                round_id=attempt,
                model_input={
                    "task_id": task.task_id,
                    "scenario": scenario,
                    "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                    "oracle_prediction": oracle_candidate.model_dump(),
                },
                model_output=det_oracle_critic.model_dump(),
            )
            if validation_feedback:
                last_oracle_feedback = validation_feedback
                continue

            recorder.record(
                agent_role="agent6_oracle_predictor",
                step=f"oracle_prediction_{scenario_slug}",
                round_id=attempt,
                model_input=oracle_in,
                model_output=oracle_candidate.model_dump(),
            )
            oracle_prediction = oracle_candidate
            break

        if oracle_prediction is None:
            fallback_reason = last_oracle_feedback or "Agent6 did not return a valid oracle prediction."
            oracle_prediction = _fallback_oracle_prediction(
                task_id=task.task_id,
                scenario=scenario,
                packet_sequence=packets_for_scenario,
                reason=fallback_reason,
            )
            scenario_oracle_prediction_status[scenario] = "FALLBACK"
            scenario_oracle_prediction_feedback[scenario] = fallback_reason
            scenario_oracle_prediction_attempts[scenario] = oracle_attempt_count
            recorder.record(
                agent_role="agent6_oracle_predictor",
                step=f"oracle_prediction_fallback_{scenario_slug}",
                round_id=max(1, oracle_attempt_count),
                model_input={"scenario": scenario, "reason": fallback_reason},
                model_output=oracle_prediction.model_dump(),
            )
        else:
            scenario_oracle_prediction_status[scenario] = "PASS"
            scenario_oracle_prediction_feedback[scenario] = "oracle prediction generated"
            scenario_oracle_prediction_attempts[scenario] = oracle_attempt_count

        scenario_outputs[scenario] = TestcaseOutput(
            program=ctx.program_name or "unknown",
            topology_ref=str(ctx.topology_path),
            topology=topo_summary,
            task_id=task.task_id,
            packet_sequence=packets_for_scenario,
            entities=last_entities.entities,
            control_plane_sequence=last_entities.control_plane_sequence,
            execution_sequence=last_entities.execution_sequence,
            oracle_prediction=oracle_prediction,
            oracle_comparison={
                "status": "PREDICTION_ONLY",
                "note": "Runtime observation comparison is intentionally out of scope in this stage.",
            },
            meta={
                "generator": "sagefuzz_seedgen",
                "timestamp_utc": _utc_ts(),
                "scenario": scenario,
                "scenario_kind": scenario_kind,
                "packet_sequence_status": last_attempt.critic.status,
                "packet_sequence_feedback": last_attempt.critic.feedback,
                "entities_status": last_entity_critic.status,
                "entities_feedback": last_entity_critic.feedback,
                "attempts_packet_sequence": attempt_count,
                "attempts_entities": entity_attempt_count,
                "control_plane_operation_count": len(last_entities.control_plane_sequence),
                "execution_operation_count": len(last_entities.execution_sequence),
                "oracle_prediction_status": scenario_oracle_prediction_status.get(scenario),
                "oracle_prediction_feedback": scenario_oracle_prediction_feedback.get(scenario),
                "attempts_oracle_prediction": scenario_oracle_prediction_attempts.get(scenario, 0),
            },
        )

    index_path, cases_dir = _resolve_output_paths(run_id, cfg.out_path)
    cases_dir.mkdir(parents=True, exist_ok=True)

    case_files: Dict[str, str] = {}
    for scenario in scenario_order:
        scenario_output = scenario_outputs.get(scenario)
        if scenario_output is None:
            continue
        case_path = cases_dir / f"{_scenario_slug(scenario)}.json"
        _write_json_file(case_path, scenario_output.model_dump())
        case_files[scenario] = str(case_path)

    all_entities_pass = bool(scenario_entity_status) and all(s == "PASS" for s in scenario_entity_status.values())
    final_status = "PASS" if (last_attempt.critic.status == "PASS" and all_entities_pass) else "FAIL"
    final_feedback = (
        f"packet_sequence: {last_attempt.critic.status} ({last_attempt.critic.feedback}); "
        f"scenario_entities: {scenario_entity_status}; "
        f"oracle_prediction: {scenario_oracle_prediction_status}"
    )

    generation_elapsed_seconds = max(0.0, time.perf_counter() - generation_start_mono)
    generation_end_ts = _utc_ts()

    case_records: List[Dict[str, Any]] = []
    for scenario in scenario_order:
        if scenario not in case_files:
            continue
        scenario_output = scenario_outputs.get(scenario)
        scenario_kind = str(scenario_meta.get(scenario, {}).get("kind") or "neutral")
        case_records.append(
            {
                "scenario": scenario,
                "scenario_slug": _scenario_slug(scenario),
                "kind": scenario_kind,
                "required": bool(scenario_meta.get(scenario, {}).get("required")),
                "case_file": case_files[scenario],
                "packet_count": len(scenario_output.packet_sequence) if scenario_output else 0,
                "entity_count": len(scenario_output.entities) if scenario_output else 0,
                "control_plane_operation_count": len(scenario_output.control_plane_sequence) if scenario_output else 0,
                "execution_operation_count": len(scenario_output.execution_sequence) if scenario_output else 0,
                "entities_status": scenario_entity_status.get(scenario),
                "entities_feedback": scenario_entity_feedback.get(scenario),
                "attempts_entities": scenario_entity_attempts.get(scenario, 0),
                "oracle_prediction_status": scenario_oracle_prediction_status.get(scenario),
                "oracle_prediction_feedback": scenario_oracle_prediction_feedback.get(scenario),
                "attempts_oracle_prediction": scenario_oracle_prediction_attempts.get(scenario, 0),
            }
        )
    cases_by_kind = _split_case_records_by_kind(case_records)

    index_payload = {
        "schema_version": "2.0",
        "run_id": run_id,
        "summary": {
            "program": ctx.program_name or "unknown",
            "topology_ref": str(ctx.topology_path),
            "task_id": task.task_id,
            "final_status": final_status,
            "final_feedback": final_feedback,
            "packet_sequence_status": last_attempt.critic.status,
            "packet_sequence_feedback": last_attempt.critic.feedback,
            "attempts_packet_sequence": attempt_count,
            "total_cases": len(case_records),
            "positive_cases": len(cases_by_kind["positive"]),
            "negative_cases": len(cases_by_kind["negative"]),
            "neutral_cases": len(cases_by_kind["neutral"]),
            "passed_case_count": sum(1 for c in case_records if c.get("entities_status") == "PASS"),
            "failed_case_count": sum(1 for c in case_records if c.get("entities_status") == "FAIL"),
            "total_control_plane_operations": sum(int(c.get("control_plane_operation_count") or 0) for c in case_records),
            "total_execution_operations": sum(int(c.get("execution_operation_count") or 0) for c in case_records),
            "oracle_prediction_pass_case_count": sum(
                1 for c in case_records if c.get("oracle_prediction_status") == "PASS"
            ),
            "oracle_prediction_fallback_case_count": sum(
                1 for c in case_records if c.get("oracle_prediction_status") == "FALLBACK"
            ),
        },
        "timing": {
            "intent_to_testcase_seconds": generation_elapsed_seconds,
            "generation_start_utc": generation_start_ts,
            "generation_end_utc": generation_end_ts,
        },
        "artifacts": {
            "cases_dir": str(cases_dir),
            "cases": case_records,
            "cases_by_kind": cases_by_kind,
        },
    }
    _write_json_file(index_path, index_payload)
    _write_json_file(session_state_path, session_state)

    return index_path
