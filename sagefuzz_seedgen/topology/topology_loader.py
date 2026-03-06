from __future__ import annotations

import ipaddress
from collections import Counter
from typing import Any, Dict, Mapping, Optional


def parse_host_ip(ip_cidr: str) -> ipaddress.IPv4Interface:
    return ipaddress.ip_interface(ip_cidr)  # type: ignore[arg-type]


def host_connected_switch(host_id: str, host_to_switch: Mapping[str, str]) -> Optional[str]:
    sw = host_to_switch.get(host_id)
    return sw if isinstance(sw, str) and sw else None


def classify_host_zone(host_id: str, *, host_to_switch: Mapping[str, str]) -> str:
    """Classify host zone conservatively.

    Only infer internal/external when topology clearly looks like a two-sided zone topology
    (exactly two host-facing switches and each side serves multiple hosts). Otherwise return unknown.
    """

    sw = host_connected_switch(host_id, host_to_switch)
    if not sw:
        return "unknown"

    counts = Counter(host_to_switch.values())
    if len(counts) != 2:
        return "unknown"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if ranked[0][1] < 2 or ranked[1][1] < 2:
        return "unknown"
    if sw == ranked[0][0]:
        return "internal"
    if sw == ranked[1][0]:
        return "external"
    return "unknown"


def summarize_topology(topology: Mapping[str, Any]) -> Dict[str, Any]:
    hosts = topology.get("hosts", {})
    links = topology.get("links", [])
    host_summary: Dict[str, Any] = {}
    if isinstance(hosts, dict):
        for hid, info in hosts.items():
            if not isinstance(hid, str) or not isinstance(info, dict):
                continue
            host_summary[hid] = {"ip": info.get("ip"), "mac": info.get("mac")}

    link_summary = links if isinstance(links, list) else []
    return {"hosts": host_summary, "links": link_summary}
