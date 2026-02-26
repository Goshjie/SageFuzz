from __future__ import annotations

import ipaddress
from typing import Any, Dict, Mapping, Optional


def parse_host_ip(ip_cidr: str) -> ipaddress.IPv4Interface:
    # Only IPv4 is needed for our current P4 examples.
    return ipaddress.ip_interface(ip_cidr)  # type: ignore[arg-type]


def host_connected_switch(host_id: str, host_to_switch: Mapping[str, str]) -> Optional[str]:
    sw = host_to_switch.get(host_id)
    return sw if isinstance(sw, str) and sw else None


def classify_host_zone(host_id: str, *, host_to_switch: Mapping[str, str]) -> str:
    """Classify a host as internal/external based on which switch it connects to.

    For the provided pod-topo, hosts connected to s1 are treated as internal and to s2 as external.
    If unknown, returns "unknown".
    """

    sw = host_connected_switch(host_id, host_to_switch)
    if sw == "s1":
        return "internal"
    if sw == "s2":
        return "external"
    return "unknown"


def summarize_topology(topology: Mapping[str, Any]) -> Dict[str, Any]:
    hosts = topology.get("hosts", {})
    links = topology.get("links", [])
    # Keep it readable and small: hosts ip/mac, links endpoints.
    host_summary: Dict[str, Any] = {}
    if isinstance(hosts, dict):
        for hid, info in hosts.items():
            if not isinstance(hid, str) or not isinstance(info, dict):
                continue
            host_summary[hid] = {"ip": info.get("ip"), "mac": info.get("mac")}

    link_summary = links if isinstance(links, list) else []
    return {"hosts": host_summary, "links": link_summary}

