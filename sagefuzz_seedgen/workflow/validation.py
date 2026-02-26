from __future__ import annotations

from typing import List, Optional, Tuple

from sagefuzz_seedgen.runtime.program_context import ProgramContext
from sagefuzz_seedgen.schemas import CriticResult, PacketSpec, TaskSpec
from sagefuzz_seedgen.topology.topology_loader import classify_host_zone


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

        syn_zone = classify_host_zone(syn.tx_host, host_to_switch=ctx.host_to_switch)
        synack_zone = classify_host_zone(synack.tx_host, host_to_switch=ctx.host_to_switch)
        ack_zone = classify_host_zone(ack.tx_host, host_to_switch=ctx.host_to_switch)

        if syn_zone != "internal":
            return CriticResult(status="FAIL", feedback=f"Positive SYN must be sent by internal host; got {syn.tx_host} ({syn_zone})")
        if synack_zone != "external":
            return CriticResult(status="FAIL", feedback=f"Positive SYN-ACK must be sent by external host; got {synack.tx_host} ({synack_zone})")
        if ack_zone != "internal":
            return CriticResult(status="FAIL", feedback=f"Positive ACK must be sent by internal host; got {ack.tx_host} ({ack_zone})")

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
                zone = classify_host_zone(p.tx_host, host_to_switch=ctx.host_to_switch)
                if zone != "external":
                    return CriticResult(
                        status="FAIL",
                        feedback="negative_external_initiation SYN must be sent by an external host.",
                    )
                break

    return CriticResult(status="PASS", feedback="Directional TCP state trigger sequence is structurally valid.")

