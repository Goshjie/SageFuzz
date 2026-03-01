from __future__ import annotations

from ipaddress import ip_interface
from typing import Any, Dict, List, Optional, Set, Tuple

from sagefuzz_seedgen.runtime.program_context import ProgramContext
from sagefuzz_seedgen.schemas import CriticResult, PacketSpec, TableRule, TaskSpec


def _get_flag(flags: object) -> str:
    if isinstance(flags, str):
        return flags
    return ""


def _field_int(fields: dict, key: str) -> Optional[int]:
    v = fields.get(key)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        # allow hex
        s = v.strip().lower()
        try:
            if s.startswith("0x"):
                return int(s, 16)
            return int(s, 10)
        except Exception:
            return None
    return None


def _field_str(fields: dict, key: str) -> Optional[str]:
    v = fields.get(key)
    return v if isinstance(v, str) else None


def _find_handshake_triplet(packets: List[PacketSpec]) -> Optional[Tuple[PacketSpec, PacketSpec, PacketSpec]]:
    # Heuristic: find SYN, then SYN-ACK, then ACK.
    syn = None
    synack = None
    ack = None
    for p in packets:
        flags = _get_flag(p.fields.get("TCP.flags"))
        if syn is None and "S" in flags and "A" not in flags:
            syn = p
            continue
        if syn is not None and synack is None and "S" in flags and "A" in flags:
            synack = p
            continue
        if syn is not None and synack is not None and ack is None and "A" in flags and "S" not in flags:
            ack = p
            break
    if syn and synack and ack:
        return syn, synack, ack
    return None


def validate_directional_tcp_state_trigger(
    *,
    ctx: ProgramContext,
    task: TaskSpec,
    packet_sequence: List[PacketSpec],
) -> CriticResult:
    """Deterministic validator for the current stage DoD.

    We validate:
    - topology binding: tx_host exists, internal initiates, external replies
    - minimal time-ordered TCP state trigger (SYN -> SYN-ACK -> ACK)
    - parser magic numbers for Ethernet/IPv4/TCP (best-effort)
    """

    if not packet_sequence:
        return CriticResult(status="FAIL", feedback="packet_sequence is empty")

    # Topology presence
    for p in packet_sequence:
        if p.tx_host not in ctx.host_info:
            return CriticResult(status="FAIL", feedback=f"packet_id {p.packet_id}: tx_host '{p.tx_host}' not in topology hosts")

    # Find positive handshake
    trip = _find_handshake_triplet(packet_sequence)
    if trip is None and task.require_positive_handshake:
        return CriticResult(
            status="FAIL",
            feedback="Missing positive directional TCP handshake triplet (SYN -> SYN-ACK -> ACK).",
        )

    if trip is not None:
        syn, synack, ack = trip

        # Directionality is intent-driven: use explicit host roles from TaskSpec (derived from user intent).
        if syn.tx_host != task.internal_host:
            return CriticResult(
                status="FAIL",
                feedback=f"Positive SYN must be sent by internal_host '{task.internal_host}'; got '{syn.tx_host}'.",
            )
        if synack.tx_host != task.external_host:
            return CriticResult(
                status="FAIL",
                feedback=f"Positive SYN-ACK must be sent by external_host '{task.external_host}'; got '{synack.tx_host}'.",
            )
        if ack.tx_host != task.internal_host:
            return CriticResult(
                status="FAIL",
                feedback=f"Positive ACK must be sent by internal_host '{task.internal_host}'; got '{ack.tx_host}'.",
            )

        syn_seq = _field_int(syn.fields, "TCP.seq")
        synack_seq = _field_int(synack.fields, "TCP.seq")
        synack_ack = _field_int(synack.fields, "TCP.ack")
        ack_ack = _field_int(ack.fields, "TCP.ack")

        if syn_seq is None or synack_seq is None or synack_ack is None or ack_ack is None:
            return CriticResult(status="FAIL", feedback="Handshake packets must include TCP.seq and TCP.ack where applicable.")

        if synack_ack != syn_seq + 1:
            return CriticResult(status="FAIL", feedback="SYN-ACK TCP.ack must equal SYN TCP.seq + 1.")
        if ack_ack != synack_seq + 1:
            return CriticResult(status="FAIL", feedback="ACK TCP.ack must equal SYN-ACK TCP.seq + 1.")

        # Best-effort magic numbers (do not overfit; just catch obvious omissions)
        for pkt in (syn, synack, ack):
            ether = _field_str(pkt.fields, "Ethernet.etherType")
            if ether is None:
                return CriticResult(status="FAIL", feedback=f"packet_id {pkt.packet_id}: missing Ethernet.etherType magic number (expected 0x0800 for IPv4)")
            if ether.lower() != "0x0800":
                return CriticResult(status="FAIL", feedback=f"packet_id {pkt.packet_id}: Ethernet.etherType must be 0x0800 for IPv4")

            proto = _field_int(pkt.fields, "IPv4.proto")
            if proto is None:
                return CriticResult(status="FAIL", feedback=f"packet_id {pkt.packet_id}: missing IPv4.proto (expected 6 for TCP)")
            if proto != 6:
                return CriticResult(status="FAIL", feedback=f"packet_id {pkt.packet_id}: IPv4.proto must be 6 for TCP")

    # Optional negative case: external initiation SYN
    if task.include_negative_external_initiation:
        for p in packet_sequence:
            if p.scenario != "negative_external_initiation":
                continue
            flags = _get_flag(p.fields.get("TCP.flags"))
            if "S" in flags and "A" not in flags:
                if p.tx_host != task.external_host:
                    return CriticResult(
                        status="FAIL",
                        feedback=f"negative_external_initiation SYN must be sent by external_host '{task.external_host}'.",
                    )
                break

    return CriticResult(status="PASS", feedback="Directional TCP state trigger sequence is structurally valid.")


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

    if task.external_host not in ctx.host_info or task.internal_host not in ctx.host_info:
        return CriticResult(status="FAIL", feedback="Task host roles are not present in topology.")

    return CriticResult(status="PASS", feedback="Control-plane entities are structurally valid and aligned with packet_sequence.")
