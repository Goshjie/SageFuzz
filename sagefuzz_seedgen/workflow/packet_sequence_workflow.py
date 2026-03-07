from __future__ import annotations

import hashlib
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
    PacketSpec,
    RuleSetCandidate,
    TableRule,
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


def _progress(message: str) -> None:
    print(f"[进度] {message}", flush=True)


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


def _normalize_test_objective(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if not token:
        return None
    mapping = {
        "1": "data_plane_behavior",
        "data": "data_plane_behavior",
        "dp": "data_plane_behavior",
        "data_plane": "data_plane_behavior",
        "data_plane_behavior": "data_plane_behavior",
        "2": "control_plane_rules",
        "cp": "control_plane_rules",
        "control": "control_plane_rules",
        "control_plane": "control_plane_rules",
        "control_plane_rules": "control_plane_rules",
    }
    if token in mapping:
        return mapping[token]
    if "数据平面" in token:
        return "data_plane_behavior"
    if "控制平面" in token:
        return "control_plane_rules"
    return None


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


def _fallback_minimal_entities(
    *,
    ctx: Any,
    task: TaskSpec,
    packet_sequence: List[PacketSpec],
) -> Optional[RuleSetCandidate]:
    ipv4_packets = [packet for packet in packet_sequence if "IPv4" in packet.protocol_stack]
    if not ipv4_packets:
        return None

    selected_table = None
    selected_action = None
    action_params: List[str] = []
    for table_name, table in ctx.tables_by_name.items():
        if not isinstance(table, dict):
            continue
        key = table.get("key", [])
        actions = table.get("actions", [])
        key_names = []
        if isinstance(key, list):
            for item in key:
                if not isinstance(item, dict):
                    continue
                target = item.get("target")
                if isinstance(target, list) and len(target) == 2:
                    key_names.append(f"hdr.{target[0]}.{target[1]}")
        if not any("dstaddr" in name.lower() for name in key_names):
            continue
        if not isinstance(actions, list):
            continue
        for action_name in actions:
            action = ctx.actions_by_name.get(action_name)
            if not isinstance(action, dict):
                continue
            runtime_data = action.get("runtime_data", []) if isinstance(action.get("runtime_data"), list) else []
            params = [item.get("name") for item in runtime_data if isinstance(item, dict) and isinstance(item.get("name"), str)]
            if params:
                selected_table = table_name
                selected_action = action_name
                action_params = params
                break
        if selected_table:
            break

    if not selected_table or not selected_action:
        return None

    rules: List[TableRule] = []
    seen_ips: set[str] = set()
    for packet in ipv4_packets:
        dst_ip = packet.fields.get("IPv4.dst")
        if not isinstance(dst_ip, str) or dst_ip in seen_ips:
            continue
        seen_ips.add(dst_ip)
        dst_mac = None
        for info in ctx.host_info.values():
            if not isinstance(info, dict):
                continue
            host_ip = str(info.get("ip") or "").split("/", 1)[0]
            if host_ip == dst_ip:
                maybe_mac = info.get("mac")
                if isinstance(maybe_mac, str):
                    dst_mac = maybe_mac
                break
        action_data = {}
        for param in action_params:
            low = param.lower()
            if low in {"dstaddr", "dstaddr_t", "dstmac", "dstaddrmac"} and isinstance(dst_mac, str):
                action_data[param] = dst_mac
            elif low in {"port", "egress_spec"}:
                action_data[param] = 1
            else:
                action_data[param] = 0
        rules.append(
            TableRule(
                table_name=selected_table,
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": [dst_ip, 32]},
                action_name=selected_action,
                action_data=action_data,
            )
        )

    if not rules:
        return None
    return RuleSetCandidate(task_id=task.task_id, entities=rules)


def _normalize_control_plane_sequence(
    candidate: RuleSetCandidate,
    *,
    operator_actions: Optional[List[ControlPlaneOperation]] = None,
) -> List[ControlPlaneOperation]:
    """Ensure testcase always contains explicit ordered control-plane operations."""
    operator_actions = list(operator_actions or [])
    if candidate.control_plane_sequence:
        combined: List[ControlPlaneOperation] = []
        for op in operator_actions:
            combined.append(op)
        for op in candidate.control_plane_sequence:
            combined.append(op)
        normalized: List[ControlPlaneOperation] = []
        next_entity_index = 1
        for idx, op in enumerate(combined, 1):
            entity_index = op.entity_index
            if op.operation_type == "apply_table_entry" and entity_index is None:
                entity_index = next_entity_index
                next_entity_index += 1
            normalized.append(op.model_copy(update={"order": idx, "entity_index": entity_index}))
        return normalized

    derived: List[ControlPlaneOperation] = []
    for op in operator_actions:
        derived.append(op)
    next_entity_index = 1
    for op in derived:
        if op.operation_type == "apply_table_entry" and isinstance(op.entity_index, int):
            next_entity_index = max(next_entity_index, op.entity_index + 1)
    for rule in candidate.entities:
        idx = next_entity_index
        next_entity_index += 1
        derived.append(
            ControlPlaneOperation(
                order=len(derived) + 1,
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
    for idx, op in enumerate(derived, 1):
        op.order = idx
    return derived


def _derive_operator_control_plane_sequence(*, task: TaskSpec, scenario: str) -> List[ControlPlaneOperation]:
    ops: List[ControlPlaneOperation] = []
    next_order = 1
    for item in task.operator_actions:
        if not hasattr(item, "timing"):
            continue
        item_scenario = getattr(item, "scenario", None)
        if item_scenario not in (None, "", scenario):
            continue
        ops.append(
            ControlPlaneOperation(
                order=next_order,
                operation_type="custom",
                target=str(getattr(item, "target", "manual_action")),
                parameters={
                    "action_type": getattr(item, "action_type", "custom"),
                    "timing": getattr(item, "timing", "before_traffic"),
                    **(getattr(item, "parameters", {}) if isinstance(getattr(item, "parameters", {}), dict) else {}),
                },
                expected_effect=getattr(item, "expected_effect", None),
            )
        )
        next_order += 1
    return ops


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
    before_ops: List[ControlPlaneOperation] = []
    after_ops: List[ControlPlaneOperation] = []
    for op in control_plane_sequence:
        timing = None
        if isinstance(op.parameters, dict):
            timing = op.parameters.get("timing")
        if timing == "after_traffic":
            after_ops.append(op)
        else:
            before_ops.append(op)

    for op in before_ops:
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

    for op in after_ops:
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

    return derived


def _compact_task_payload(task: TaskSpec) -> Dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_description": task.task_description,
        "feature_under_test": task.feature_under_test,
        "intent_category": task.intent_category,
        "observation_focus": task.observation_focus,
        "observation_method": task.observation_method,
        "expected_observation_semantics": task.expected_observation_semantics,
        "operator_actions": [item.model_dump() if hasattr(item, "model_dump") else item for item in task.operator_actions],
        "observation_requirements": [item.model_dump() if hasattr(item, "model_dump") else item for item in task.observation_requirements],
        "traffic_pattern": task.traffic_pattern,
        "role_bindings": task.role_bindings,
        "sequence_contract": [item.model_dump() if hasattr(item, "model_dump") else item for item in task.sequence_contract],
        "require_positive_and_negative": task.require_positive_and_negative,
        "generation_mode": task.generation_mode,
        "forbidden_tables": task.forbidden_tables,
    }


def _resolve_host_for_role(ctx: Any, role_bindings: Dict[str, str], role_or_host: Optional[str]) -> Optional[str]:
    if not isinstance(role_or_host, str) or not role_or_host.strip():
        return None
    token = role_or_host.strip()
    if token in role_bindings:
        return role_bindings[token]
    if token in ctx.host_info:
        return token
    return None


def _host_ip(ctx: Any, host_id: Optional[str]) -> Optional[str]:
    if not host_id:
        return None
    raw = str(ctx.host_info.get(host_id, {}).get("ip") or "")
    return raw.split("/", 1)[0] if raw else None


def _host_mac(ctx: Any, host_id: Optional[str]) -> Optional[str]:
    if not host_id:
        return None
    raw = ctx.host_info.get(host_id, {}).get("mac")
    return str(raw) if isinstance(raw, str) and raw else None


def _resolve_packet_value(
    *,
    field_name: str,
    expected: Any,
    ctx: Any,
    task: TaskSpec,
    tx_host: Optional[str],
    rx_host: Optional[str],
    packet_id: int,
    step_index: int,
) -> Any:
    if isinstance(expected, (int, float, bool)):
        return expected
    if not isinstance(expected, str):
        return expected
    token = expected.strip()
    if not token:
        return expected

    if token.endswith('_ip'):
        host_id = _resolve_host_for_role(ctx, task.role_bindings, token[:-3])
        return _host_ip(ctx, host_id) or expected
    if token.endswith('_mac'):
        host_id = _resolve_host_for_role(ctx, task.role_bindings, token[:-4])
        return _host_mac(ctx, host_id) or expected
    if token.count('.') == 1:
        role, attr = token.split('.', 1)
        host_id = _resolve_host_for_role(ctx, task.role_bindings, role)
        if attr == 'ip':
            return _host_ip(ctx, host_id) or expected
        if attr == 'mac':
            return _host_mac(ctx, host_id) or expected

    if token in {'fixed', 'fixed_single_port', 'fixed_port', 'fixed_value_1', 'fixed_value_2', 'constant', 'constant_port'} or token.startswith('fixed'):
        if field_name.endswith('dport') or field_name.endswith('dstPort'):
            return 80
        return 10000 + step_index
    if token == 'fixed_to_congest_flow':
        if field_name.endswith('dport') or field_name.endswith('dstPort'):
            return 80
        return 12000
    if token == 'new_flow_different_hash':
        if field_name.endswith('dport') or field_name.endswith('dstPort'):
            return 8080
        return 22000 + packet_id
    if token.startswith('different_'):
        return 20000 + step_index
    if token.startswith('vary') or token.startswith('flow_'):
        return 30000 + packet_id
    if token in {'incrementing', 'decrementing', 'any', 'wildcard', 'next_hop_mac', 'gateway_mac'}:
        return token
    return expected


def _repair_packet_sequence_candidate(*, ctx: Any, task: TaskSpec, candidate: PacketSequenceCandidate) -> PacketSequenceCandidate:
    scenario_packets = _group_packets_by_scenario(candidate.packet_sequence)
    repaired_packets: List[PacketSpec] = []
    for contract in task.sequence_contract:
        scenario = _scenario_name(getattr(contract, "scenario", None))
        packets = list(scenario_packets.get(scenario, []))
        cursor = 0
        for step_index, step in enumerate(contract.steps, 1):
            repeat_count = max(1, int(getattr(step, "repeat_count", 1)))
            tx_host = _resolve_host_for_role(ctx, task.role_bindings, getattr(step, "tx_role", None))
            rx_host = _resolve_host_for_role(ctx, task.role_bindings, getattr(step, "rx_role", None))
            for repeat_offset in range(repeat_count):
                if cursor < len(packets):
                    packet = packets[cursor]
                    cursor += 1
                    payload = packet.model_dump()
                else:
                    payload = {
                        "packet_id": len(repaired_packets) + 1,
                        "tx_host": tx_host or cfg.default_initiator_host if False else tx_host,
                        "scenario": scenario,
                        "protocol_stack": list(step.protocol_stack),
                        "fields": {},
                    }
                payload["scenario"] = scenario
                if tx_host:
                    payload["tx_host"] = tx_host
                if step.protocol_stack:
                    payload["protocol_stack"] = list(step.protocol_stack)
                fields = dict(payload.get("fields") or {})
                if tx_host:
                    tx_ip = _host_ip(ctx, tx_host)
                    tx_mac = _host_mac(ctx, tx_host)
                    if tx_ip and "IPv4" in payload["protocol_stack"]:
                        fields.setdefault("IPv4.src", tx_ip)
                    if tx_mac and "Ethernet" in payload["protocol_stack"]:
                        fields.setdefault("Ethernet.src", tx_mac)
                if rx_host:
                    rx_ip = _host_ip(ctx, rx_host)
                    rx_mac = _host_mac(ctx, rx_host)
                    if rx_ip and "IPv4" in payload["protocol_stack"]:
                        fields.setdefault("IPv4.dst", rx_ip)
                    if rx_mac and "Ethernet" in payload["protocol_stack"] and fields.get("Ethernet.dst") in (None, '', '00:00:00:00:00:00'):
                        fields["Ethernet.dst"] = rx_mac
                if "IPv4" in payload["protocol_stack"]:
                    fields.setdefault("IPv4.proto", 6 if "TCP" in payload["protocol_stack"] else 17 if "UDP" in payload["protocol_stack"] else 1)
                    fields.setdefault("Ethernet.etherType", '0x0800')
                    fields.setdefault("IPv4.totalLength", 40 if "TCP" in payload["protocol_stack"] else 28 if "UDP" in payload["protocol_stack"] else 20)
                    fields.setdefault("IPv4.hdrChecksum", 0)
                for field_name, expected in getattr(step, 'field_expectations', {}).items():
                    if not isinstance(field_name, str) or '.' not in field_name:
                        continue
                    resolved = _resolve_packet_value(
                        field_name=field_name,
                        expected=expected,
                        ctx=ctx,
                        task=task,
                        tx_host=tx_host,
                        rx_host=rx_host,
                        packet_id=int(payload.get("packet_id") or len(repaired_packets) + 1),
                        step_index=step_index + repeat_offset,
                    )
                    if isinstance(expected, str) and (expected.startswith('vary') or expected.startswith('flow_') or expected.startswith('different_')):
                        if field_name.endswith('sport') or field_name.endswith('srcPort'):
                            resolved = 40000 + len(repaired_packets) + 1
                        elif field_name.endswith('dport') or field_name.endswith('dstPort'):
                            resolved = 50000 + step_index
                    if resolved not in {'incrementing', 'decrementing', 'any', 'wildcard', 'next_hop_mac', 'gateway_mac'}:
                        fields[field_name] = resolved
                payload["fields"] = fields
                repaired_packets.append(PacketSpec.model_validate(payload))
        # keep any remaining packets for the scenario
        for packet in packets[cursor:]:
            repaired_packets.append(packet)
    return PacketSequenceCandidate(task_id=candidate.task_id, packet_sequence=repaired_packets)


def _fallback_packet_sequence_from_task(*, ctx: Any, task: TaskSpec) -> Optional[PacketSequenceCandidate]:
    packets: List[PacketSpec] = []
    packet_id = 1
    for scenario_index, contract in enumerate(task.sequence_contract, 1):
        if not hasattr(contract, 'steps'):
            continue
        scenario_name = _scenario_name(getattr(contract, 'scenario', None))
        for step_index, step in enumerate(contract.steps, 1):
            if not hasattr(step, 'protocol_stack'):
                continue
            tx_host = _resolve_host_for_role(ctx, task.role_bindings, getattr(step, 'tx_role', None))
            rx_host = _resolve_host_for_role(ctx, task.role_bindings, getattr(step, 'rx_role', None))
            if tx_host is None:
                continue
            repeat_count = max(1, int(getattr(step, 'repeat_count', 1)))
            for repeat_offset in range(repeat_count):
                fields: Dict[str, Any] = {}
                if 'Ethernet' in step.protocol_stack:
                    fields['Ethernet.src'] = _host_mac(ctx, tx_host) or '00:00:00:00:00:01'
                    fields['Ethernet.dst'] = _host_mac(ctx, rx_host) or '00:00:00:00:00:fe'
                    if len(step.protocol_stack) >= 2 and step.protocol_stack[1] == 'IPv4':
                        fields['Ethernet.etherType'] = '0x0800'
                if 'IPv4' in step.protocol_stack:
                    fields['IPv4.src'] = _host_ip(ctx, tx_host) or '10.0.0.1'
                    if rx_host:
                        fields['IPv4.dst'] = _host_ip(ctx, rx_host) or '10.0.0.2'
                    fields.setdefault('IPv4.proto', 6 if 'TCP' in step.protocol_stack else 17 if 'UDP' in step.protocol_stack else 1)
                    fields.setdefault('IPv4.totalLength', 40 if 'TCP' in step.protocol_stack else 28 if 'UDP' in step.protocol_stack else 20)
                    fields.setdefault('IPv4.hdrChecksum', 0)
                if 'TCP' in step.protocol_stack:
                    fields.setdefault('TCP.sport', 10000 + step_index if repeat_count == 1 else 10000 + packet_id)
                    fields.setdefault('TCP.dport', 80)
                    fields.setdefault('TCP.flags', '0x10')
                if 'UDP' in step.protocol_stack:
                    fields.setdefault('UDP.sport', 20000 + step_index if repeat_count == 1 else 20000 + packet_id)
                    fields.setdefault('UDP.dport', 3000)
                for field_name, expected in getattr(step, 'field_expectations', {}).items():
                    if not isinstance(field_name, str) or '.' not in field_name:
                        continue
                    resolved = _resolve_packet_value(
                        field_name=field_name,
                        expected=expected,
                        ctx=ctx,
                        task=task,
                        tx_host=tx_host,
                        rx_host=rx_host,
                        packet_id=packet_id,
                        step_index=step_index,
                    )
                    if resolved not in {'incrementing', 'decrementing', 'any', 'wildcard', 'next_hop_mac', 'gateway_mac'}:
                        fields[field_name] = resolved
                packets.append(
                    PacketSpec(
                        packet_id=packet_id,
                        tx_host=tx_host,
                        scenario=scenario_name,
                        protocol_stack=list(step.protocol_stack),
                        fields=fields,
                    )
                )
                packet_id += 1
    if not packets:
        return None
    return PacketSequenceCandidate(task_id=task.task_id, packet_sequence=packets)


def _is_non_packet_stage_feedback(feedback: Optional[str]) -> bool:
    if not isinstance(feedback, str):
        return False
    low = feedback.lower()
    markers = [
        'control_plane',
        'control-plane',
        'entities',
        'execution_sequence',
        'execution sequence',
        'operator_actions',
        'observation_requirements',
        'rule_setcandidate',
    ]
    return any(marker in low for marker in markers)


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

    order_values = [int(item.sequence_order) for item in prediction.packet_predictions]
    if len(set(order_values)) != len(order_values):
        return "packet_predictions contains duplicate sequence_order."

    ordered_by_step = sorted(prediction.packet_predictions, key=lambda item: int(item.sequence_order))
    ordered_packet_ids = [int(item.packet_id) for item in ordered_by_step]
    if ordered_packet_ids != expected_ids:
        return (
            "packet_predictions sequence_order does not match packet_sequence order; "
            f"expected packet ids {expected_ids}, got {ordered_packet_ids}."
        )

    for item in prediction.packet_predictions:
        if item.expected_outcome == "deliver" and not _as_non_empty_str(item.expected_rx_host):
            return f"packet_id {item.packet_id}: expected_outcome=deliver requires expected_rx_host."
        if not _as_non_empty_str(item.processing_decision):
            return f"packet_id {item.packet_id}: processing_decision must be non-empty."
        if not _as_non_empty_str(item.expected_switch_state_before):
            return f"packet_id {item.packet_id}: expected_switch_state_before must be non-empty."
        if not _as_non_empty_str(item.expected_switch_state_after):
            return f"packet_id {item.packet_id}: expected_switch_state_after must be non-empty."
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
            sequence_order=idx,
            expected_outcome="unknown",
            processing_decision="unknown_due_to_fallback",
            expected_switch_state_before="unknown",
            expected_switch_state_after="unknown",
            expected_observation="fallback_unknown",
            rationale=reason,
        )
        for idx, packet in enumerate(packet_sequence, 1)
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


def _apply_initial_intent_answer(
    *,
    intent_payload: Dict[str, Any],
    full_intent: str,
    test_objective: Optional[str],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(intent_payload)
    if full_intent:
        # Keep initial intake minimal: orchestrator captures raw complete intent text,
        # and Agent1 decides whether clarifying questions are needed.
        merged["intent_text"] = full_intent
        # Lightweight task-family hinting only. Avoid hardcoding specific program names.
        if not _as_non_empty_str(merged.get("feature_under_test")):
            low = full_intent.lower()
            if any(token in low for token in ("telemetry", "monitor", "observe", "measurement", "probe")):
                merged["feature_under_test"] = "traffic_monitoring"
            elif any(token in full_intent for token in ("监控", "监测", "观测", "遥测", "测量", "利用率")):
                merged["feature_under_test"] = "traffic_monitoring"
            elif any(token in low for token in ("firewall", "acl", "access control", "policy")):
                merged["feature_under_test"] = "policy_validation"
            elif any(token in full_intent for token in ("防火墙", "策略", "访问控制")):
                merged["feature_under_test"] = "policy_validation"
            elif any(token in low for token in ("route", "routing", "forward", "lpm", "next hop")):
                merged["feature_under_test"] = "forwarding_behavior"
            elif any(token in full_intent for token in ("转发", "路由", "下一跳", "路径验证")):
                merged["feature_under_test"] = "forwarding_behavior"
    if test_objective:
        merged["test_objective"] = test_objective
    return merged


def _collect_initial_intent(intent_payload: Dict[str, Any]) -> Dict[str, Any]:
    print("\n[初始化输入] 请输入本轮完整测试意图：")
    default_intent = _as_non_empty_str(intent_payload.get("intent_text")) or _as_non_empty_str(
        intent_payload.get("feature_under_test")
    )

    full_intent = _prompt_with_default(
        "请输入完整意图（可包含功能/策略/拓扑/角色约束）:",
        default_intent,
    )
    default_objective = _normalize_test_objective(str(intent_payload.get("test_objective") or ""))
    objective_hint = "数据平面行为(1, 默认，生成包+规则) / 控制平面规则(2，仅生成包)"
    objective_raw = _prompt_with_default(
        f"请选择测试目标 [{objective_hint}]:",
        "1" if default_objective is None else ("1" if default_objective == "data_plane_behavior" else "2"),
    )
    test_objective = _normalize_test_objective(objective_raw)
    if test_objective is None:
        # Conservative fallback to current default behavior.
        test_objective = "data_plane_behavior"
    return _apply_initial_intent_answer(
        intent_payload=intent_payload,
        full_intent=full_intent,
        test_objective=test_objective,
    )


def _intent_memory_labels(intent_payload: Dict[str, Any]) -> List[str]:
    texts = []
    for field in ("feature_under_test", "intent_text"):
        value = _as_non_empty_str(intent_payload.get(field))
        if value:
            texts.append(value.lower())
    joined = " ".join(texts)

    labels: List[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    objective = _normalize_test_objective(str(intent_payload.get("test_objective") or ""))
    if objective == "data_plane_behavior":
        add("data_plane")
    elif objective == "control_plane_rules":
        add("control_plane")

    if any(token in joined for token in ("monitor", "monitoring", "telemetry", "observe", "measurement", "probe", "latency", "利用率", "监控", "监测", "观测", "遥测")):
        add("measurement_observation")
    if any(token in joined for token in ("register", "counter", "meter", "state query", "观测对象", "状态读取")):
        add("state_query")
    if any(token in joined for token in ("firewall", "acl", "access control", "policy", "防火墙", "策略", "访问控制")):
        add("communication_policy")
    if any(token in joined for token in ("route", "routing", "forward", "lpm", "next hop", "转发", "路由", "下一跳")):
        add("forwarding_behavior")
    if any(token in joined for token in ("path", "link", "segment", "路径", "链路", "链路段")):
        add("path_behavior")
    if any(token in joined for token in ("stateful", "有状态", "conntrack", "connection tracking")):
        add("stateful_logic")
    if any(token in joined for token in ("balance", "ecmp", "load distribution", "负载均衡", "分流")):
        add("load_distribution")
    if any(token in joined for token in ("multicast", "replication", "broadcast", "组播", "复制")):
        add("replication_behavior")

    has_initiation = any(token in joined for token in ("initiate", "initiates", "initiation", "initiator", "发起", "主动"))
    has_reply = any(token in joined for token in ("reply", "response", "return traffic", "回包", "回复", "响应"))
    has_allow = any(token in joined for token in ("allow", "permit", "success", "通过", "允许", "成功"))
    has_block = any(token in joined for token in ("block", "blocked", "deny", "drop", "forbid", "禁止", "阻止", "不行", "失败", "丢弃"))
    if has_initiation and has_allow and has_block:
        add("directional_behavior")
    if has_initiation and has_reply:
        add("bidirectional_exchange")

    if ("communication_policy" not in labels) and any(token in joined for token in ("tcp", "syn", "syn-ack", "ack", "三次握手", "握手")):
        add("transport_handshake")

    return labels


def _normalize_intent_for_memory_bucket(intent_payload: Dict[str, Any]) -> str:
    texts = []
    for field in ("feature_under_test", "intent_text"):
        value = _as_non_empty_str(intent_payload.get(field))
        if value:
            texts.append(value.lower())
    objective = _normalize_test_objective(str(intent_payload.get("test_objective") or ""))
    if objective:
        texts.append(objective.lower())

    normalized = " ".join(texts)
    normalized = re.sub(r"\bh\d+\b", " host ", normalized)
    normalized = re.sub(r"\b(?:s\d+|sw\d+|switch\d+)\b", " switch ", normalized)
    normalized = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", " ip ", normalized)
    normalized = re.sub(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", " mac ", normalized)
    normalized = re.sub(r"[a-z0-9_./-]+\.p4\b", " p4_source ", normalized)
    normalized = re.sub(r"\bmyingress\.[a-z0-9_.]+\b", " table ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _derive_intent_memory_bucket(intent_payload: Dict[str, Any]) -> str:
    labels = _intent_memory_labels(intent_payload)
    if labels:
        priority = [
            "data_plane",
            "control_plane",
            "measurement_observation",
            "state_query",
            "communication_policy",
            "forwarding_behavior",
            "path_behavior",
            "stateful_logic",
            "load_distribution",
            "replication_behavior",
            "directional_behavior",
            "bidirectional_exchange",
            "transport_handshake",
        ]
        ordered = [label for label in priority if label in labels]
        extra = [label for label in labels if label not in ordered]
        return "intent-" + "-".join((ordered + extra)[:6])
    normalized = _normalize_intent_for_memory_bucket(intent_payload)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"intent-generic-{digest}"


def _resolve_memory_user_id(*, cfg: RunConfig, intent_payload: Dict[str, Any]) -> str:
    base_user_id = (cfg.memory.user_id or "sagefuzz-local-user").strip() or "sagefuzz-local-user"
    bucket = _derive_intent_memory_bucket(intent_payload)
    return f"{base_user_id}:{bucket}"


def _infer_operator_actions_from_intent(*, intent_payload: Dict[str, Any], task: TaskSpec) -> List[Dict[str, Any]]:
    intent_text = str(intent_payload.get("intent_text") or "")
    combined = " ".join(
        [
            intent_text,
            str(intent_payload.get("operator_constraints") or ""),
            str(task.task_description or ""),
            str(task.expected_observation_semantics or ""),
        ]
    )
    actions: List[Dict[str, Any]] = []
    next_order = 1

    threshold_match = re.search(r"(?:阈值[^0-9]{0,8}|threshold[^0-9]{0,8})(\d+)", combined, re.IGNORECASE)
    if threshold_match and any(token in combined.lower() for token in ["manual", "人工", "调低", "override", "threshold"]):
        actions.append(
            {
                "order": next_order,
                "action_type": "manual_threshold_override",
                "timing": "before_traffic",
                "scenario": None,
                "target": "PACKET_THRESHOLD",
                "parameters": {"new_value": int(threshold_match.group(1))},
                "expected_effect": f"threshold manually set to {threshold_match.group(1)} before traffic",
            }
        )
        next_order += 1

    link_match = re.search(r"(s\d+\s*-\s*s\d+)", combined, re.IGNORECASE)
    if link_match and any(token in combined.lower() for token in ["断开", "fail", "failure", "down"]):
        link_id = link_match.group(1).replace(" ", "")
        actions.append(
            {
                "order": next_order,
                "action_type": "manual_link_event",
                "timing": "between_scenarios",
                "scenario": None,
                "target": link_id,
                "parameters": {"event_type": "link_failure", "link_id": link_id},
                "expected_effect": f"{link_id} is manually failed before failover validation",
            }
        )
        next_order += 1

    if any(token in combined.lower() for token in ["notify controller", "通知控制器", "重收敛", "reconvergence", "reconverge"]):
        actions.append(
            {
                "order": next_order,
                "action_type": "manual_controller_notify",
                "timing": "between_scenarios",
                "scenario": None,
                "target": "controller",
                "parameters": {"trigger_reconvergence": True},
                "expected_effect": "controller is notified to recompute forwarding state",
            }
        )
        next_order += 1

    if any(token in combined.lower() for token in ["inject congestion", "拥塞", "高带宽", "congestion"]):
        actions.append(
            {
                "order": next_order,
                "action_type": "custom",
                "timing": "between_scenarios",
                "scenario": "congestion_reroute",
                "target": "primary_path",
                "parameters": {"method": "extra_high_rate_flows", "path_id": "primary_path"},
                "expected_effect": "extra traffic is injected to create congestion on the currently selected primary path before reroute validation",
            }
        )

    return actions


def _infer_observation_requirements_from_intent(*, intent_payload: Dict[str, Any], task: TaskSpec) -> List[Dict[str, Any]]:
    intent_text = " ".join(
        [
            str(intent_payload.get("intent_text") or ""),
            str(intent_payload.get("expected_observation") or ""),
            str(task.observation_method or ""),
            str(task.expected_observation_semantics or ""),
        ]
    )
    low = intent_text.lower()
    out: List[Dict[str, Any]] = []
    if any(token in low for token in ["path telemetry", "telemetry", "port stats", "端口统计", "路径利用率", "path utilization"]):
        out.append(
            {
                "order": 1,
                "action_type": "read_counter",
                "target_hint": "path_utilization_counters_before",
                "timing": "after_scenario",
                "purpose": "capture baseline path/port utilization before congestion reroute comparison",
            }
        )
        out.append(
            {
                "order": 2,
                "action_type": "read_counter",
                "target_hint": "path_utilization_counters_after",
                "timing": "after_scenario",
                "purpose": "capture post-congestion path/port utilization to compare reroute behavior",
            }
        )
    return out


def _apply_observation_fallback(*, intent_payload: Dict[str, Any], task: TaskSpec) -> TaskSpec:
    if task.observation_requirements:
        return task
    inferred = _infer_observation_requirements_from_intent(intent_payload=intent_payload, task=task)
    if not inferred:
        return task
    payload = task.model_dump()
    payload["observation_requirements"] = inferred
    return TaskSpec.model_validate(payload)


def _apply_load_distribution_fallback(*, intent_payload: Dict[str, Any], task: TaskSpec) -> TaskSpec:
    if task.intent_category != "load_distribution":
        return task
    payload = task.model_dump()

    operator_actions = list(payload.get("operator_actions") or [])
    for action in operator_actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_type") == "manual_threshold_override":
            action["scenario"] = None
        if action.get("action_type") == "custom" and action.get("target") == "congestion_injection":
            params = action.setdefault("parameters", {})
            if isinstance(params, dict):
                params.setdefault("path_id", "primary_path")
                params.setdefault("method", "extra_high_rate_flows")
            action.setdefault("timing", "between_scenarios")

    obs = list(payload.get("observation_requirements") or [])
    if isinstance(obs, list) and len(obs) == 1:
        obs.append(
            {
                "order": 2,
                "action_type": "read_register",
                "target_hint": "path_selection_state",
                "timing": "after_scenario",
                "purpose": "verify path-selection state changes after congestion-triggered reroute",
            }
        )
    payload["observation_requirements"] = obs

    contracts = list(payload.get("sequence_contract") or [])
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        scenario = str(contract.get("scenario") or "")
        steps = contract.get("steps") or []
        if not isinstance(steps, list):
            continue
        if scenario.startswith("positive_normal") or "load_distribution" in scenario:
            for step in steps:
                if isinstance(step, dict):
                    step["repeat_count"] = max(int(step.get("repeat_count", 1)), 10)
        if "congestion" in scenario:
            for idx, step in enumerate(steps, 1):
                if not isinstance(step, dict):
                    continue
                step["repeat_count"] = max(int(step.get("repeat_count", 1)), 5)
                if idx == 1:
                    step["traffic_profile"] = "high_rate_congestion_build"
                else:
                    step["traffic_profile"] = "post_congestion_new_flows"
            contract["scenario_goal"] = contract.get("scenario_goal") or "build congestion on one path, then verify new flows reroute to alternate paths"
            contract["expected_observation"] = contract.get("expected_observation") or "path utilization on the congested path rises before new flows are redirected to other paths"
    payload["sequence_contract"] = contracts

    return TaskSpec.model_validate(payload)


def _apply_operator_action_fallback(*, intent_payload: Dict[str, Any], task: TaskSpec) -> TaskSpec:
    inferred = _infer_operator_actions_from_intent(intent_payload=intent_payload, task=task)
    if not inferred:
        return task
    existing = [item.model_dump() if hasattr(item, "model_dump") else item for item in task.operator_actions]
    existing_types = {str(item.get("action_type")) for item in existing if isinstance(item, dict)}
    merged = list(existing)
    next_order = max([int(item.get("order", 0)) for item in existing if isinstance(item, dict)] + [0]) + 1
    for item in inferred:
        action_type = str(item.get("action_type"))
        if action_type in existing_types:
            continue
        item = dict(item)
        item["order"] = next_order
        next_order += 1
        merged.append(item)
    if merged == existing:
        return task
    payload = task.model_dump()
    payload["operator_actions"] = merged
    return TaskSpec.model_validate(payload)


def _resolve_generation_mode(*, intent_payload: Dict[str, Any], task: TaskSpec) -> str:
    selected = _normalize_test_objective(str(intent_payload.get("test_objective") or ""))
    if selected == "control_plane_rules":
        return "packet_only"
    if selected == "data_plane_behavior":
        return "packet_and_entities"
    # Fallback to task-provided value if user selection is unavailable.
    return task.generation_mode


def run_packet_sequence_generation(cfg: RunConfig) -> Path:
    run_id = _utc_ts()
    recorder = AgentRecorder(base_dir=Path("runs"), run_id=run_id)

    ctx = initialize_program_context(
        bmv2_json_path=cfg.program.bmv2_json,
        graphs_dir=cfg.program.graphs_dir,
        p4info_path=cfg.program.p4info_txtpb,
        topology_path=cfg.program.topology_json,
        p4_source_path=cfg.program.p4_source,
    )
    set_program_context(ctx)
    if not isinstance(ctx.p4_source_code, str) or not ctx.p4_source_code:
        _progress("未加载P4源码（paths.p4_source为空），相关源码查询工具将返回 unavailable。")
    else:
        _progress(f"已加载P4源码: {ctx.p4_source_path}")

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
            "p4_source": str(cfg.program.p4_source) if cfg.program.p4_source else None,
        }
    )

    if cfg.model is None:
        raise ValueError("ModelConfig is required to run agents.")

    install_agno_argument_patch()

    # --- Step 1: Collect initial full intent text; Agent1 handles clarification questions ---
    intent_payload: Dict[str, Any] = dict(cfg.user_intent) if isinstance(cfg.user_intent, dict) else {}
    intent_payload = _collect_initial_intent(intent_payload)

    memory_user_id = cfg.memory.user_id
    memory_bucket = None
    if cfg.memory.enabled:
        memory_bucket = _derive_intent_memory_bucket(intent_payload)
        memory_user_id = _resolve_memory_user_id(cfg=cfg, intent_payload=intent_payload)
        _progress(
            f"已启用Agno memory: db={cfg.memory.db_path}, bucket={memory_bucket}, user_id={memory_user_id}"
        )
    else:
        _progress("Agno memory 已禁用。")

    session_state["run_config"].update(
        {
            "agno_memory_enabled": cfg.memory.enabled,
            "agno_memory_user_id": memory_user_id if cfg.memory.enabled else None,
            "agno_memory_bucket": memory_bucket,
            "agno_memory_db_path": str(cfg.memory.db_path) if cfg.memory.enabled else None,
        }
    )

    agent1, agent2, agent3, agent4, agent5, agent6, _team = build_agents_and_team(
        model_cfg=cfg.model,
        prompts_dir=Path("prompts"),
        memory_cfg=cfg.memory,
        memory_user_id=memory_user_id,
        session_id_prefix=run_id,
    )
    # Agent1 receives its system prompt at construction time. Then we collect fixed user inputs.
    recorder.record(
        agent_role="agent1_semantic_analyzer",
        step="initial_intent_intake",
        round_id=0,
        model_input={"source": "single_raw_intent"},
        model_output={"user_intent": intent_payload or None},
    )

    # --- Step 2: Semantic analyzer produces a task spec, or asks model-driven follow-up questions ---
    max_intent_rounds = 5
    task: TaskSpec | None = None
    agent1_feedback: Optional[str] = None
    last_task_candidate: Optional[TaskSpec] = None
    last_task_review_feedback: Optional[str] = None
    _progress("已接收意图，开始Agent1语义分析。")
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
        a1_raw: Any = None
        a1_raw_retry: Any = None
        a1_primary_error: Optional[str] = None
        a1_retry_error: Optional[str] = None
        _progress(
            f"Agent1 正在执行语义分析（第{_round}/{max_intent_rounds}轮，schema模式，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
        )
        try:
            a1_raw = agent1.run(
                a1_in_str,
                output_schema=Agent1Output,
                session_state=session_state,
            ).content
            a1_out = _coerce_schema_output(a1_raw, Agent1Output)
        except Exception as e:
            a1_out = None
            a1_primary_error = _error_text(e)

        if a1_out is None:
            # Retry once without schema forcing; then coerce locally from raw content.
            _progress(
                f"Agent1 首次输出解析失败，正在进行原始输出重试（当前阶段：Agent1 第{_round}/{max_intent_rounds}轮，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
            )
            try:
                _progress("Agent1 原始输出重试调用已发出，正在等待模型返回。")
                a1_raw_retry = agent1.run(
                    a1_in_str,
                    session_state=session_state,
                ).content
                a1_out = _coerce_schema_output(a1_raw_retry, Agent1Output)
            except Exception as e:
                a1_retry_error = _error_text(e)

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
            extra={
                "raw_output": _to_recordable(a1_raw),
                "raw_output_retry": _to_recordable(a1_raw_retry),
                "primary_error": a1_primary_error,
                "retry_error": a1_retry_error,
            },
        )

        if a1_out.kind == "task" and a1_out.task is not None:
            a1_out.task = _apply_operator_action_fallback(intent_payload=intent_payload, task=a1_out.task)
            a1_out.task = _apply_observation_fallback(intent_payload=intent_payload, task=a1_out.task)
            a1_out.task = _apply_load_distribution_fallback(intent_payload=intent_payload, task=a1_out.task)
            last_task_candidate = a1_out.task
            _progress("Agent1 已生成TaskSpec，转交Agent3进行语义完整性审查。")
            # Agent-based semantic completeness check for TaskSpec before Agent2 generation.
            task_review_in = {
                "mode": "task_contract_review",
                "task": a1_out.task.model_dump(),
                "user_intent": intent_payload or None,
                "review_hint": (
                    "Check whether sequence_contract semantically matches user intent. "
                    "For stateful/directional intents, positive scenario should be a full ordered transaction "
                    "(not collapsed to one packet). "
                    "If intent says communication should succeed after permitted initiation, positive scenario must "
                    "prove bidirectional communication (at least one packet each direction). "
                    "For telemetry/monitoring intents (e.g., link monitor), ensure sequence_contract includes "
                    "observation-driving packets (such as probe/measurement packets), task.observation_focus/"
                    "expected_observation_semantics are populated, and do not require policy-style negative scenarios "
                    "unless user intent explicitly asks for them. "
                    "If telemetry intent success depends on utilization/counter/register change, the task should not "
                    "collapse to a single decorative packet unless user intent explicitly says one probe is enough. "
                    "If parser/source evidence shows a dedicated probe/query header path, the task must use that exact "
                    "custom packet format rather than a generic UDP query packet. "
                    "For load-distribution or congestion-aware load-balancing intents, it is acceptable to model congestion injection as an operator action plus a later reroute scenario; do not require pseudo-packets for operator actions or explicit scenario-phase fields if the contract already encodes baseline load, congestion trigger, and post-congestion verification. "
                    "For policy-correctness verification intents, ensure task.forbidden_tables captures the "
                    "policy-enforcing table(s) that should be intentionally left unconfigured."
                ),
            }
            task_review_in_str = (
                "Review TaskSpec semantic completeness and return CriticResult STRICT JSON:\n\n"
                + json.dumps(task_review_in, indent=2)
            )
            try:
                _progress(
                f"Agent3 正在审查TaskSpec语义（第{_round}/{max_intent_rounds}轮，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
            )
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
                _progress("Agent3 审查未通过，已将反馈回传Agent1修订。")
                agent1_feedback = task_review.feedback
                last_task_review_feedback = task_review.feedback
                continue

            _progress("TaskSpec 语义审查通过，进入生成阶段。")
            task = a1_out.task
            break

        # Ask user and build a UserIntent object
        qs = a1_out.questions or []
        _progress("Agent1 需要补充信息，正在等待用户输入。")
        print("\n[Agent1 needs more intent input]")
        if not qs:
            # Safety fallback if the model returned no structured questions.
            print("1. 请补充本次测试的完整意图信息（功能点、策略、拓扑与角色约束）。")
            qs = [
                # Keep fallback minimal; Agent1 is the primary intent clarifier.
                {
                    "field": "intent_text",
                    "question_zh": "请补充完整 intent_text（包含功能点、策略、拓扑与角色约束）:",
                    "required": True,
                },
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
            elif field == "topology_mapping":
                # Keep backward compatibility with prompt variants that ask for topology_mapping.
                answers["topology_zone_mapping"] = ans
                answers[field] = ans
            else:
                answers[field] = ans

        # Merge answers into existing intent (if any)
        intent_payload.update(answers)

    if task is None and last_task_candidate is not None:
        # Fallback: avoid hard stop when semantic reviewer remains unstable across rounds.
        task = last_task_candidate
        fallback_feedback = last_task_review_feedback or "TaskSpec review did not converge within max rounds."
        print(
            "\n[WARN] Agent1/Agent3 task review未在轮次内收敛，"
            "将使用最后一个TaskSpec继续执行。"
        )
        recorder.record(
            agent_role="deterministic_validator",
            step="task_contract_review_fallback_accept",
            round_id=max_intent_rounds,
            model_input={"task": task.model_dump()},
            model_output={"status": "PASS_WITH_FALLBACK", "feedback": fallback_feedback},
        )

    if task is None:
        raise RuntimeError("Unable to obtain sufficient user intent to generate a task.")

    try:
        user_intent = UserIntent.model_validate(intent_payload) if intent_payload else None
    except Exception:
        user_intent = None
    user_intent_payload = user_intent.model_dump() if user_intent else (intent_payload or None)

    # Ensure role bindings are present if the model omitted them. Prefer neutral role names
    # so non-policy tasks are not forced into initiator/responder framing.
    if not task.role_bindings:
        task.role_bindings = {
            "host_a": cfg.default_initiator_host,
            "host_b": cfg.default_responder_host,
        }
    if not task.sequence_contract:
        raise RuntimeError("TaskSpec.sequence_contract is empty. Agent1 must define scenario contracts.")
    task.generation_mode = _resolve_generation_mode(intent_payload=intent_payload, task=task)

    topo = summarize_topology(ctx.topology)
    topo_summary = TopologySummary(hosts=topo["hosts"], links=topo["links"])

    generation_start_ts = _utc_ts()
    generation_start_mono = time.perf_counter()

    last_feedback: Optional[str] = None
    last_attempt: Optional[AttemptResult] = None
    attempt_count: int = 0

    # --- Step 3: Generate packet_sequence with critic loop ---
    _progress("开始Agent2/Agent3循环生成并审查packet_sequence。")
    for attempt in range(1, cfg.max_retries + 1):
        attempt_count = attempt
        role_binding_host_info = {
            role: {
                "host_id": host_id,
                "ip": ctx.host_info.get(host_id, {}).get("ip"),
                "mac": ctx.host_info.get(host_id, {}).get("mac"),
                "switch": ctx.host_to_switch.get(host_id),
            }
            for role, host_id in task.role_bindings.items()
        }
        gen_in = {
            "attempt": attempt,
            "task": _compact_task_payload(task),
            "user_intent": user_intent_payload,
            "role_binding_host_info": role_binding_host_info,
            "topology": topo_summary.model_dump(),
            "previous_feedback": last_feedback,
        }
        gen_in_str = (
            "Generate PacketSequenceCandidate STRICT JSON. Input:\n\n" + json.dumps(gen_in, indent=2)
        )
        try:
            _progress(
                f"Agent2 正在生成packet_sequence（第{attempt}/{cfg.max_retries}轮，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
            )
            cand_raw = agent2.run(
                gen_in_str,
                output_schema=PacketSequenceCandidate,
                session_state=session_state,
            ).content
        except Exception as e:
            last_feedback = f"Agent2 API error: {_error_text(e)}"
            _progress(f"Agent2 调用失败：{last_feedback}")
            recorder.record(
                agent_role="agent2_sequence_constructor",
                step="packet_sequence_candidate",
                round_id=attempt,
                model_input=gen_in,
                model_output={"error": "agent_run_exception", "message": _error_text(e)},
            )
            continue
        candidate = _coerce_schema_output(cand_raw, PacketSequenceCandidate)
        if candidate is not None:
            candidate = _repair_packet_sequence_candidate(ctx=ctx, task=task, candidate=candidate)
        if candidate is None:
            last_feedback = "Agent2 schema parse failed (possibly timeout/non-JSON output)."
            _progress(f"Agent2 输出解析失败：{last_feedback}")
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
            "task": _compact_task_payload(task),
            "user_intent": user_intent_payload,
            "packet_sequence_candidate": candidate.model_dump(),
        }
        critic_in_str = "Evaluate candidate and return CriticResult STRICT JSON:\n\n" + json.dumps(critic_in, indent=2)
        try:
            _progress(
                f"Agent3 正在审查packet_sequence（第{attempt}/{cfg.max_retries}轮，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
            )
            critic_raw = agent3.run(
                critic_in_str,
                output_schema=CriticResult,
                session_state=session_state,
            ).content
        except Exception as e:
            last_feedback = f"Agent3 API error: {_error_text(e)}"
            _progress(f"Agent3 调用失败：{last_feedback}")
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
            _progress(f"Agent3 输出解析失败：{last_feedback}")
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
        elif attempt_result.critic.status == "FAIL" and _is_non_packet_stage_feedback(attempt_result.critic.feedback):
            attempt_result.critic = CriticResult(
                status="PASS",
                feedback="Packet sequence passes deterministic validation; ignoring non-packet-stage critic feedback.",
            )
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
            _progress("packet_sequence 已通过审查与确定性校验。")
            break
        _progress(f"packet_sequence 未通过，准备重试。原因：{last_feedback}")

    if last_attempt is None:
        fallback_candidate = _fallback_packet_sequence_from_task(ctx=ctx, task=task)
        if fallback_candidate is None:
            raise RuntimeError(
                f"No packet_sequence attempt succeeded after {cfg.max_retries} retries. Last feedback: {last_feedback}"
            )
        fallback_critic = validate_packet_sequence_contract(ctx=ctx, task=task, packet_sequence=fallback_candidate.packet_sequence)
        last_attempt = AttemptResult(task_id=task.task_id, packet_sequence=fallback_candidate.packet_sequence, critic=fallback_critic)
        recorder.record(
            agent_role="deterministic_validator",
            step="packet_sequence_fallback",
            round_id=cfg.max_retries + 1,
            model_input={"task": task.model_dump()},
            model_output={
                "packet_sequence": [p.model_dump() for p in fallback_candidate.packet_sequence],
                "critic": fallback_critic.model_dump(),
            },
        )
        last_feedback = fallback_critic.feedback

    # --- Step 4: Generate control-plane entities per scenario ---
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
    entity_generation_required = task.generation_mode == "packet_and_entities"
    _progress("开始按场景生成控制面实体与Oracle预测。")

    for scenario in scenario_order:
        packets_for_scenario = scenario_packets_map.get(scenario, [])
        if not packets_for_scenario:
            if bool(scenario_meta.get(scenario, {}).get("required")):
                raise RuntimeError(f"Required scenario '{scenario}' has no packets in packet_sequence.")
            continue

        scenario_slug = _scenario_slug(scenario)
        scenario_kind = str(scenario_meta.get(scenario, {}).get("kind") or "neutral")
        _progress(f"处理场景 '{scenario}'（kind={scenario_kind}, packets={len(packets_for_scenario)}）。")
        last_entity_feedback: Optional[str] = None
        operator_cp_sequence = _derive_operator_control_plane_sequence(task=task, scenario=scenario)
        last_entities: Optional[RuleSetCandidate] = None
        last_entity_critic: Optional[CriticResult] = None
        entity_attempt_count = 0

        if entity_generation_required:
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
                    _progress(
                        f"Agent4 正在生成场景'{scenario}'的控制面实体（第{attempt}/{cfg.max_retries}轮）。"
                    )
                    entity_raw = agent4.run(
                        entity_gen_in_str,
                        output_schema=RuleSetCandidate,
                        session_state=session_state,
                    ).content
                except Exception as e:
                    last_entity_feedback = f"Agent4 API error: {_error_text(e)}"
                    _progress(f"Agent4 调用失败：{last_entity_feedback}")
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
                    _progress(f"Agent4 输出解析失败：{last_entity_feedback}")
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
                normalized_cp_sequence = _normalize_control_plane_sequence(entity_candidate, operator_actions=operator_cp_sequence)
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
                    _progress(
                        f"Agent5 正在审查场景'{scenario}'控制面实体（第{attempt}/{cfg.max_retries}轮）。"
                    )
                    entity_critic_raw = agent5.run(
                        entity_critic_in_str,
                        output_schema=CriticResult,
                        session_state=session_state,
                    ).content
                except Exception as e:
                    last_entity_feedback = f"Agent5 API error: {_error_text(e)}"
                    _progress(f"Agent5 调用失败：{last_entity_feedback}")
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
                    _progress(f"Agent5 输出解析失败：{last_entity_feedback}")
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
                    _progress(f"场景'{scenario}'的实体生成已通过审查。")
                    break
                failure_text = (last_entity_feedback or "").lower()
                deterministic_fallback_markers = [
                    "entities is empty",
                    "unknown table",
                    "not allowed by table",
                    "missing action_data",
                ]
                if any(marker in failure_text for marker in deterministic_fallback_markers):
                    _progress(f"场景'{scenario}'实体失败属于可确定性兜底类型，跳过剩余重试并进入fallback。原因：{last_entity_feedback}")
                    break
                _progress(f"场景'{scenario}'实体未通过，准备重试。原因：{last_entity_feedback}")

            fallback_needed = (
                last_entities is None
                or last_entity_critic is None
                or getattr(last_entity_critic, "status", "FAIL") != "PASS"
                or not getattr(last_entities, "entities", [])
            )
            if fallback_needed:
                fallback_candidate = _fallback_minimal_entities(
                    ctx=ctx,
                    task=task,
                    packet_sequence=packets_for_scenario,
                )
                if fallback_candidate is None:
                    raise RuntimeError(
                        f"No entity generation attempt succeeded for scenario '{scenario}' after {cfg.max_retries} retries. "
                        f"Last feedback: {last_entity_feedback}"
                    )
                normalized_cp_sequence = _normalize_control_plane_sequence(
                    fallback_candidate,
                    operator_actions=operator_cp_sequence,
                )
                normalized_execution_sequence = _normalize_execution_sequence(
                    candidate=fallback_candidate,
                    packet_sequence=packets_for_scenario,
                    control_plane_sequence=normalized_cp_sequence,
                )
                last_entities = fallback_candidate.model_copy(
                    update={
                        "control_plane_sequence": normalized_cp_sequence,
                        "execution_sequence": normalized_execution_sequence,
                    }
                )
                last_entity_critic = CriticResult(
                    status="PASS",
                    feedback="Using deterministic minimal forwarding fallback entities.",
                )
                recorder.record(
                    agent_role="deterministic_validator",
                    step=f"entity_fallback_{scenario_slug}",
                    round_id=cfg.max_retries + 1,
                    model_input={
                        "scenario": scenario,
                        "packet_sequence": [p.model_dump() for p in packets_for_scenario],
                    },
                    model_output=last_entities.model_dump(),
                )

            scenario_entity_status[scenario] = last_entity_critic.status
            scenario_entity_feedback[scenario] = last_entity_critic.feedback
            scenario_entity_attempts[scenario] = entity_attempt_count
        else:
            # packet_only mode: skip Agent4/5 while preserving a deterministic
            # execution timeline for packet replay and oracle prediction.
            _progress(f"当前为packet_only模式，场景'{scenario}'跳过Agent4/Agent5，直接转交Agent6。")
            empty_candidate = RuleSetCandidate(task_id=task.task_id, entities=[])
            normalized_cp_sequence: List[ControlPlaneOperation] = _derive_operator_control_plane_sequence(task=task, scenario=scenario)
            normalized_execution_sequence = _normalize_execution_sequence(
                candidate=empty_candidate,
                packet_sequence=packets_for_scenario,
                control_plane_sequence=normalized_cp_sequence,
            )
            last_entities = empty_candidate.model_copy(
                update={
                    "control_plane_sequence": normalized_cp_sequence,
                    "execution_sequence": normalized_execution_sequence,
                }
            )
            skip_feedback = "Skipped by generation_mode=packet_only."
            scenario_entity_status[scenario] = "SKIPPED"
            scenario_entity_feedback[scenario] = skip_feedback
            scenario_entity_attempts[scenario] = 0
            recorder.record(
                agent_role="deterministic_validator",
                step=f"entity_generation_skipped_{scenario_slug}",
                round_id=0,
                model_input={
                    "scenario": scenario,
                    "task_generation_mode": task.generation_mode,
                    "packet_count": len(packets_for_scenario),
                },
                model_output={"status": "SKIPPED", "feedback": skip_feedback},
            )

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
                _progress(
                    f"Agent6 正在生成场景'{scenario}'的Oracle预测（第{attempt}/{cfg.max_retries}轮，最长等待约{int(cfg.model.timeout_seconds) if cfg.model else 0}s）。"
                )
                oracle_raw = agent6.run(
                    oracle_in_str,
                    output_schema=OraclePredictionCandidate,
                    session_state=session_state,
                ).content
            except Exception as e:
                last_oracle_feedback = f"Agent6 API error: {_error_text(e)}"
                _progress(f"Agent6 调用失败：{last_oracle_feedback}")
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
                _progress(f"Agent6 输出解析失败：{last_oracle_feedback}")
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
                _progress(f"Agent6 输出未通过确定性校验，准备重试。原因：{validation_feedback}")
                continue

            recorder.record(
                agent_role="agent6_oracle_predictor",
                step=f"oracle_prediction_{scenario_slug}",
                round_id=attempt,
                model_input=oracle_in,
                model_output=oracle_candidate.model_dump(),
            )
            oracle_prediction = oracle_candidate
            _progress(f"场景'{scenario}'的Oracle预测已生成。")
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
            _progress(f"场景'{scenario}'的Oracle预测使用fallback。")
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
                "note": "Prediction-only mode: oracle output includes expected_rx_host and per-packet state transitions.",
            },
            meta={
                "generator": "sagefuzz_seedgen",
                "timestamp_utc": _utc_ts(),
                "generation_mode": task.generation_mode,
                "scenario": scenario,
                "scenario_kind": scenario_kind,
                "packet_sequence_status": last_attempt.critic.status,
                "packet_sequence_feedback": last_attempt.critic.feedback,
                "entities_status": scenario_entity_status.get(scenario),
                "entities_feedback": scenario_entity_feedback.get(scenario),
                "attempts_packet_sequence": attempt_count,
                "attempts_entities": scenario_entity_attempts.get(scenario, 0),
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

    all_entities_ok = bool(scenario_entity_status) and all(
        s in {"PASS", "SKIPPED"} for s in scenario_entity_status.values()
    )
    final_status = "PASS" if (last_attempt.critic.status == "PASS" and all_entities_ok) else "FAIL"
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
            "generation_mode": task.generation_mode,
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
            "skipped_case_count": sum(1 for c in case_records if c.get("entities_status") == "SKIPPED"),
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
