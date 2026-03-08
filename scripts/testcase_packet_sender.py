#!/usr/bin/env python3
import argparse
import json
import os
import time
from typing import Any

from scapy.arch import get_if_list
from scapy.fields import BitField, ByteField, IntField
from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.l2 import Ether
from scapy.packet import Packet, Raw, bind_layers
from scapy.sendrecv import sendp

TYPE_PROBE = 0x0812


class Probe(Packet):
    name = "Probe"
    fields_desc = [ByteField("hop_cnt", 0)]


class ProbeData(Packet):
    name = "ProbeData"
    fields_desc = [
        BitField("bos", 0, 1),
        BitField("swid", 0, 7),
        ByteField("port", 0),
        IntField("byte_cnt", 0),
        BitField("last_time", 0, 48),
        BitField("cur_time", 0, 48),
    ]


class ProbeFwd(Packet):
    name = "ProbeFwd"
    fields_desc = [ByteField("egress_spec", 0)]


bind_layers(Ether, Probe, type=TYPE_PROBE)
bind_layers(Probe, ProbeFwd, hop_cnt=0)
bind_layers(Probe, ProbeData)
bind_layers(ProbeData, ProbeData, bos=0)
bind_layers(ProbeData, ProbeFwd, bos=1)
bind_layers(ProbeFwd, ProbeFwd)


FLAG_MAP = {
    "SYN": "S",
    "ACK": "A",
    "SYN+ACK": "SA",
    "FIN": "F",
    "RST": "R",
    "PSH": "P",
    "URG": "U",
}


def _normalize_int(v: Any) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 0)
    raise ValueError(f"Unsupported int value: {v!r}")


def _tcp_flags(v: Any) -> Any:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        if v.startswith("0x"):
            return int(v, 16)
        return FLAG_MAP.get(v, v)
    return v


def _pick_iface() -> str:
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    raise RuntimeError("Cannot find eth0 interface")


def _build_packet(pkt_def: dict) -> Packet:
    stack = pkt_def.get("protocol_stack", [])
    fields = pkt_def.get("fields", {})

    ether = Ether(
        src=fields.get("Ethernet.src"),
        dst=fields.get("Ethernet.dst"),
        type=_normalize_int(fields.get("Ethernet.etherType", 0x0800)),
    )
    pkt: Packet = ether

    if "IPv4" in stack:
        proto = fields.get("IPv4.proto", fields.get("IPv4.protocol", 0))
        ip = IP(
            src=fields.get("IPv4.src"),
            dst=fields.get("IPv4.dst"),
            version=_normalize_int(fields.get("IPv4.version", 4)),
            ihl=_normalize_int(fields.get("IPv4.ihl", 5)),
            tos=_normalize_int(fields.get("IPv4.diffserv", 0)),
            len=_normalize_int(fields.get("IPv4.totalLength", fields.get("IPv4.totalLen", 20 if "TCP" not in stack and "UDP" not in stack else 40))),
            id=_normalize_int(fields.get("IPv4.identification", 1)),
            flags=_normalize_int(fields.get("IPv4.flags", 0)),
            frag=_normalize_int(fields.get("IPv4.fragOffset", 0)),
            ttl=_normalize_int(fields.get("IPv4.ttl", 64)),
            proto=_normalize_int(proto),
            chksum=_normalize_int(fields.get("IPv4.hdrChecksum", 0)),
        )
        pkt = pkt / ip

    if "TCP" in stack:
        tcp = TCP(
            sport=_normalize_int(fields.get("TCP.sport", 12345)),
            dport=_normalize_int(fields.get("TCP.dport", 80)),
            seq=_normalize_int(fields.get("TCP.seq", fields.get("TCP.seqNo", 0))),
            ack=_normalize_int(fields.get("TCP.ack", fields.get("TCP.ackNo", 0))),
            dataofs=_normalize_int(fields.get("TCP.dataOffset", 5)),
            reserved=_normalize_int(fields.get("TCP.reserved", fields.get("TCP.res", 0))),
            flags=_tcp_flags(fields.get("TCP.flags", 0)),
            window=_normalize_int(fields.get("TCP.window", 8192)),
            chksum=_normalize_int(fields.get("TCP.checksum", 0)),
            urgptr=_normalize_int(fields.get("TCP.urgentPtr", 0)),
        )
        pkt = pkt / tcp
    elif "UDP" in stack:
        udp = UDP(
            sport=_normalize_int(fields.get("UDP.sport", 12345)),
            dport=_normalize_int(fields.get("UDP.dport", 80)),
        )
        pkt = pkt / udp
    elif "probe" in stack:
        probe = Probe(hop_cnt=_normalize_int(fields.get("probe.hop_cnt", 0)))
        pkt = pkt / probe
        probe_fwd_fields = []
        explicit = [k for k in fields if k.startswith("probe_fwd")]
        if explicit:
            # current testcases only use a single probe_fwd header
            probe_fwd_fields.append(_normalize_int(fields.get("probe_fwd.egress_spec", 0)))
        else:
            probe_fwd_fields.append(_normalize_int(fields.get("probe_fwd.egress_spec", 0)))
        for egress_spec in probe_fwd_fields:
            pkt = pkt / ProbeFwd(egress_spec=egress_spec)

    payload = fields.get("Raw.load")
    if payload is not None:
        pkt = pkt / Raw(load=payload)

    return pkt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("testcase_json")
    parser.add_argument("--packet-id", type=int, action="append", default=[])
    parser.add_argument("--iface")
    parser.add_argument("--inter-packet-delay", type=float, default=0.05)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    with open(args.testcase_json, "r", encoding="utf-8") as fh:
        testcase = json.load(fh)

    packet_defs = testcase.get("packet_sequence", [])
    if args.packet_id:
        wanted = set(args.packet_id)
        packet_defs = [pkt for pkt in packet_defs if pkt.get("packet_id") in wanted]

    iface = args.iface or _pick_iface()
    for _ in range(args.count):
        for pkt_def in packet_defs:
            pkt = _build_packet(pkt_def)
            sendp(pkt, iface=iface, verbose=False)
            time.sleep(args.inter_packet_delay)


if __name__ == "__main__":
    main()
