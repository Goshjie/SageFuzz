from __future__ import annotations

from ipaddress import ip_interface
from typing import Any, Dict, List, Optional, Set

from sagefuzz_seedgen.runtime.program_context import ProgramContext
from sagefuzz_seedgen.schemas import (
    CriticResult,
    PacketSpec,
    SequenceScenarioSpec,
    TableRule,
    TaskSpec,
)


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if not raw:
            return None
        try:
            if raw.startswith("0x"):
                return float(int(raw, 16))
            return float(raw)
        except Exception:
            return None
    return None


def _coerce_literal(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            return normalized
        numeric = _to_number(normalized)
        if numeric is not None:
            # Preserve integer semantics when possible.
            return int(numeric) if numeric.is_integer() else numeric
        return normalized
    return value


def _expectation_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if "equals" in expected and not _expectation_matches(actual, expected["equals"]):
            return False
        if "eq" in expected and not _expectation_matches(actual, expected["eq"]):
            return False

        if "contains" in expected:
            needle = expected["contains"]
            if isinstance(needle, str):
                if not isinstance(actual, str) or needle not in actual:
                    return False
            elif isinstance(needle, list):
                if not isinstance(actual, str):
                    return False
                for item in needle:
                    if not isinstance(item, str) or item not in actual:
                        return False
            else:
                return False
        if "not_contains" in expected:
            needle = expected["not_contains"]
            if isinstance(needle, str):
                if not isinstance(actual, str) or needle in actual:
                    return False
            elif isinstance(needle, list):
                if not isinstance(actual, str):
                    return False
                for item in needle:
                    if not isinstance(item, str):
                        return False
                    if item in actual:
                        return False
            else:
                return False
        if "one_of" in expected:
            candidates = expected["one_of"]
            if not isinstance(candidates, list):
                return False
            actual_normalized = _coerce_literal(actual)
            normalized_candidates = [_coerce_literal(item) for item in candidates]
            if actual_normalized not in normalized_candidates:
                return False
        return True

    left = _coerce_literal(actual)
    right = _coerce_literal(expected)
    return left == right


def _scenario_packets(packet_sequence: List[PacketSpec], scenario: str) -> List[PacketSpec]:
    out: List[PacketSpec] = []
    for packet in packet_sequence:
        packet_scenario = packet.scenario or "default"
        if packet_scenario == scenario:
            out.append(packet)
    return out


def _compare_numeric(left: float, right: float, op: str) -> bool:
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
    if op == "gt":
        return left > right
    if op == "lt":
        return left < right
    if op == "ge":
        return left >= right
    if op == "le":
        return left <= right
    return False


def _validate_scenario_contract(
    *,
    ctx: ProgramContext,
    role_bindings: Dict[str, str],
    packet_sequence: List[PacketSpec],
    contract: SequenceScenarioSpec,
) -> Optional[CriticResult]:
    scenario_packets = _scenario_packets(packet_sequence, contract.scenario)
    if not scenario_packets and contract.required:
        return CriticResult(status="FAIL", feedback=f"Missing required scenario '{contract.scenario}'.")
    if not scenario_packets:
        return None

    if len(scenario_packets) < len(contract.steps):
        return CriticResult(
            status="FAIL",
            feedback=(
                f"Scenario '{contract.scenario}' has {len(scenario_packets)} packet(s), "
                f"but contract requires at least {len(contract.steps)} step(s)."
            ),
        )
    if not contract.allow_additional_packets and len(scenario_packets) != len(contract.steps):
        return CriticResult(
            status="FAIL",
            feedback=(
                f"Scenario '{contract.scenario}' must have exactly {len(contract.steps)} packet(s); "
                f"got {len(scenario_packets)}."
            ),
        )

    for idx, step in enumerate(contract.steps, 1):
        packet = scenario_packets[idx - 1]
        expected_tx_host = role_bindings.get(step.tx_role)
        if expected_tx_host is None:
            return CriticResult(
                status="FAIL",
                feedback=f"Scenario '{contract.scenario}' step {idx}: unknown tx_role '{step.tx_role}'.",
            )
        if packet.tx_host != expected_tx_host:
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"Scenario '{contract.scenario}' step {idx}: tx_host must be "
                    f"'{expected_tx_host}' for role '{step.tx_role}', got '{packet.tx_host}'."
                ),
            )

        if step.protocol_stack and packet.protocol_stack != step.protocol_stack:
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"Scenario '{contract.scenario}' step {idx}: protocol_stack mismatch; "
                    f"expected {step.protocol_stack}, got {packet.protocol_stack}."
                ),
            )

        if step.rx_role:
            expected_rx_host = role_bindings.get(step.rx_role)
            if expected_rx_host is None:
                return CriticResult(
                    status="FAIL",
                    feedback=f"Scenario '{contract.scenario}' step {idx}: unknown rx_role '{step.rx_role}'.",
                )
            host_info = ctx.host_info.get(expected_rx_host, {})
            expected_ip = _normalize_ipv4(host_info.get("ip"))
            packet_dst_ip = _normalize_ipv4(packet.fields.get("IPv4.dst"))
            if expected_ip and packet_dst_ip and packet_dst_ip != expected_ip:
                return CriticResult(
                    status="FAIL",
                    feedback=(
                        f"Scenario '{contract.scenario}' step {idx}: IPv4.dst must target role "
                        f"'{step.rx_role}' host '{expected_rx_host}' ({expected_ip}); got '{packet_dst_ip}'."
                    ),
                )
            expected_mac = host_info.get("mac")
            packet_dst_mac = packet.fields.get("Ethernet.dst")
            if isinstance(expected_mac, str) and isinstance(packet_dst_mac, str):
                if packet_dst_mac.lower() != expected_mac.lower():
                    return CriticResult(
                        status="FAIL",
                        feedback=(
                            f"Scenario '{contract.scenario}' step {idx}: Ethernet.dst must target role "
                            f"'{step.rx_role}' host '{expected_rx_host}' ({expected_mac}); got '{packet_dst_mac}'."
                        ),
                    )

        for field, expected in step.field_expectations.items():
            actual = packet.fields.get(field)
            if not _expectation_matches(actual, expected):
                return CriticResult(
                    status="FAIL",
                    feedback=(
                        f"Scenario '{contract.scenario}' step {idx}: field '{field}' violates expectation; "
                        f"actual={actual!r}, expected={expected!r}."
                    ),
                )

    for relation in contract.field_relations:
        if relation.left_step > len(scenario_packets) or relation.right_step > len(scenario_packets):
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"Scenario '{contract.scenario}' relation references out-of-range step "
                    f"(left={relation.left_step}, right={relation.right_step})."
                ),
            )
        left_packet = scenario_packets[relation.left_step - 1]
        right_packet = scenario_packets[relation.right_step - 1]
        left_value = _to_number(left_packet.fields.get(relation.left_field))
        right_value = _to_number(right_packet.fields.get(relation.right_field))
        if left_value is None or right_value is None:
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"Scenario '{contract.scenario}' relation requires numeric fields "
                    f"{relation.left_field}/{relation.right_field}."
                ),
            )
        rhs = right_value + relation.right_delta
        if not _compare_numeric(left_value, rhs, relation.op):
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"Scenario '{contract.scenario}' relation failed: step {relation.left_step}.{relation.left_field} "
                    f"({left_value}) {relation.op} step {relation.right_step}.{relation.right_field} "
                    f"+ {relation.right_delta} ({rhs})."
                ),
            )

    return None


def validate_packet_sequence_contract(
    *,
    ctx: ProgramContext,
    task: TaskSpec,
    packet_sequence: List[PacketSpec],
) -> CriticResult:
    """Deterministic validator for contract-driven packet sequences."""

    if not packet_sequence:
        return CriticResult(status="FAIL", feedback="packet_sequence is empty")

    for packet in packet_sequence:
        if packet.tx_host not in ctx.host_info:
            return CriticResult(
                status="FAIL",
                feedback=f"packet_id {packet.packet_id}: tx_host '{packet.tx_host}' not in topology hosts.",
            )

    if not task.role_bindings:
        return CriticResult(status="FAIL", feedback="task.role_bindings is empty.")
    for role, host_id in task.role_bindings.items():
        if host_id not in ctx.host_info:
            return CriticResult(
                status="FAIL",
                feedback=f"task.role_bindings[{role!r}] references unknown host '{host_id}'.",
            )

    if not task.sequence_contract:
        return CriticResult(status="FAIL", feedback="task.sequence_contract is empty.")

    if task.require_positive_and_negative:
        required_positive = [c for c in task.sequence_contract if c.required and c.kind == "positive"]
        required_negative = [c for c in task.sequence_contract if c.required and c.kind == "negative"]
        if not required_positive:
            return CriticResult(
                status="FAIL",
                feedback=(
                    "task.require_positive_and_negative=true, but sequence_contract has no required positive scenario."
                ),
            )
        if not required_negative:
            return CriticResult(
                status="FAIL",
                feedback=(
                    "task.require_positive_and_negative=true, but sequence_contract has no required negative scenario."
                ),
            )

    for contract in task.sequence_contract:
        res = _validate_scenario_contract(
            ctx=ctx,
            role_bindings=task.role_bindings,
            packet_sequence=packet_sequence,
            contract=contract,
        )
        if res is not None:
            return res

    if task.require_positive_and_negative:
        packet_scenarios = {packet.scenario or "default" for packet in packet_sequence}
        kind_by_scenario = {contract.scenario: contract.kind for contract in task.sequence_contract}
        has_positive = any(kind_by_scenario.get(scenario) == "positive" for scenario in packet_scenarios)
        has_negative = any(kind_by_scenario.get(scenario) == "negative" for scenario in packet_scenarios)
        if not has_positive or not has_negative:
            return CriticResult(
                status="FAIL",
                feedback=(
                    "packet_sequence must include both positive and negative scenarios when "
                    "task.require_positive_and_negative=true."
                ),
            )

    return CriticResult(status="PASS", feedback="packet_sequence satisfies task.sequence_contract.")


def _normalize_ipv4(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if "/" in raw:
            return str(ip_interface(raw).ip)
        return str(ip_interface(f"{raw}/32").ip)
    except Exception:
        return None


def _extract_packet_destination_ips(packet_sequence: List[PacketSpec]) -> Set[str]:
    dst_ips: Set[str] = set()
    for packet in packet_sequence:
        if "IPv4" not in packet.protocol_stack:
            continue
        ip = _normalize_ipv4(packet.fields.get("IPv4.dst"))
        if ip:
            dst_ips.add(ip)
    return dst_ips


def _extract_rule_destination_ips(rule: TableRule) -> Set[str]:
    out: Set[str] = set()
    for key, value in rule.match_keys.items():
        if "dstaddr" not in key.lower() and "ipv4.dst" not in key.lower():
            continue
        if isinstance(value, str):
            ip = _normalize_ipv4(value)
            if ip:
                out.add(ip)
            continue
        if isinstance(value, (list, tuple)) and value:
            ip = _normalize_ipv4(value[0])
            if ip:
                out.add(ip)
            continue
        if isinstance(value, dict):
            for candidate in (value.get("value"), value.get("ip"), value.get("addr")):
                ip = _normalize_ipv4(candidate)
                if ip:
                    out.add(ip)
                    break
    return out


def _normalize_table_key_field(key: Any) -> Optional[str]:
    if not isinstance(key, dict):
        return None
    target = key.get("target")
    if isinstance(target, list) and len(target) == 2 and all(isinstance(x, str) for x in target):
        return f"hdr.{target[0]}.{target[1]}"
    if isinstance(target, str):
        return target
    return None


def _normalize_match_type(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _collect_table_match_types(table_keys: Any) -> Set[str]:
    out: Set[str] = set()
    if not isinstance(table_keys, list):
        return out
    for item in table_keys:
        if not isinstance(item, dict):
            continue
        match_type = _normalize_match_type(item.get("match_type"))
        if match_type:
            out.add(match_type)
    return out


def validate_control_plane_entities(
    *,
    ctx: ProgramContext,
    task: TaskSpec,
    packet_sequence: List[PacketSpec],
    entities: List[TableRule],
) -> CriticResult:
    """Deterministic validator for generated control-plane table rules."""

    if not entities:
        return CriticResult(status="FAIL", feedback="entities is empty; at least one table rule is required.")

    packet_dst_ips = _extract_packet_destination_ips(packet_sequence)
    covered_ips: Set[str] = set()

    for idx, rule in enumerate(entities, 1):
        table = ctx.tables_by_name.get(rule.table_name)
        if not isinstance(table, dict):
            return CriticResult(status="FAIL", feedback=f"entity[{idx}]: unknown table '{rule.table_name}'.")

        table_actions = table.get("actions", [])
        if not (isinstance(table_actions, list) and rule.action_name in table_actions):
            return CriticResult(
                status="FAIL",
                feedback=f"entity[{idx}]: action '{rule.action_name}' is not allowed by table '{rule.table_name}'.",
            )

        table_keys = table.get("key", [])
        key_match_types = _collect_table_match_types(table_keys)
        rule_match_type = _normalize_match_type(rule.match_type)
        if key_match_types and rule_match_type not in key_match_types:
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"entity[{idx}]: match_type '{rule.match_type}' is incompatible with table "
                    f"'{rule.table_name}' key match type(s) {sorted(key_match_types)}."
                ),
            )

        if key_match_types.intersection({"ternary", "range", "optional"}) and rule.priority is None:
            return CriticResult(
                status="FAIL",
                feedback=(
                    f"entity[{idx}]: table '{rule.table_name}' requires priority for ternary/range/optional matches."
                ),
            )

        if isinstance(table_keys, list):
            required_key_fields = {
                field for field in (_normalize_table_key_field(item) for item in table_keys) if field is not None
            }
            missing = sorted(field for field in required_key_fields if field not in rule.match_keys)
            if missing:
                return CriticResult(
                    status="FAIL",
                    feedback=f"entity[{idx}]: missing required match key(s) {missing} for table '{rule.table_name}'.",
                )

        action = ctx.actions_by_name.get(rule.action_name)
        if isinstance(action, dict):
            runtime_data = action.get("runtime_data", [])
            required_params = []
            if isinstance(runtime_data, list):
                required_params = [item.get("name") for item in runtime_data if isinstance(item, dict)]
            missing_params = [p for p in required_params if isinstance(p, str) and p not in rule.action_data]
            if missing_params:
                return CriticResult(
                    status="FAIL",
                    feedback=f"entity[{idx}]: missing action_data parameter(s) {missing_params} for action '{rule.action_name}'.",
                )

        covered_ips.update(_extract_rule_destination_ips(rule))

    # Keep rule generation aligned with packet sequence intent:
    # destination IPs seen in packet_sequence should be covered by at least one table entry.
    if packet_dst_ips:
        uncovered = sorted(ip for ip in packet_dst_ips if ip not in covered_ips)
        if uncovered:
            return CriticResult(
                status="FAIL",
                feedback=f"entities do not cover packet_sequence destination IP(s): {uncovered}.",
            )

    if not task.role_bindings:
        return CriticResult(status="FAIL", feedback="task.role_bindings is empty.")
    missing_role_hosts = sorted(
        f"{role}:{host_id}" for role, host_id in task.role_bindings.items() if host_id not in ctx.host_info
    )
    if missing_role_hosts:
        return CriticResult(
            status="FAIL",
            feedback=f"Task role binding host(s) are not present in topology: {missing_role_hosts}.",
        )

    return CriticResult(status="PASS", feedback="Control-plane entities are structurally valid and aligned with packet_sequence.")
