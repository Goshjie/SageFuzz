from __future__ import annotations

from typing import Any, Dict, List

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context
from sagefuzz_seedgen.topology.topology_loader import classify_host_zone as _classify_host_zone


def get_topology_hosts() -> Dict[str, Dict[str, Any]]:
    """Return topology hosts with ip/mac."""
    ctx = get_program_context()
    out: Dict[str, Dict[str, Any]] = {}
    for hid, info in ctx.host_info.items():
        out[hid] = {"ip": info.get("ip"), "mac": info.get("mac")}
    return out


def get_topology_links() -> List[List[str]]:
    """Return raw topology links."""
    ctx = get_program_context()
    links = ctx.topology.get("links", [])
    return links if isinstance(links, list) else []


def get_host_info(host_id: str) -> Dict[str, Any]:
    """Return host info (ip/mac/commands) and its connected switch evidence."""
    ctx = get_program_context()
    info = ctx.host_info.get(host_id, {})
    sw = ctx.host_to_switch.get(host_id)
    return {"host_id": host_id, "ip": info.get("ip"), "mac": info.get("mac"), "switch": sw, "commands": info.get("commands")}


def classify_host_zone(host_id: str) -> Dict[str, Any]:
    """Classify host as internal/external based on topology evidence."""
    ctx = get_program_context()
    zone = _classify_host_zone(host_id, host_to_switch=ctx.host_to_switch)
    return {"host_id": host_id, "zone": zone, "evidence": {"switch": ctx.host_to_switch.get(host_id)}}


def choose_default_host_pair() -> Dict[str, Any]:
    """Choose a default (internal_client, external_peer) pair from topology."""
    ctx = get_program_context()
    internal: List[str] = []
    external: List[str] = []
    for hid in sorted(ctx.host_info.keys()):
        zone = _classify_host_zone(hid, host_to_switch=ctx.host_to_switch)
        if zone == "internal":
            internal.append(hid)
        elif zone == "external":
            external.append(hid)

    # Fallback to h1/h3 if classification yields nothing.
    internal_client = internal[0] if internal else "h1"
    external_peer = external[0] if external else "h3"
    return {"internal_client": internal_client, "external_peer": external_peer}


get_topology_hosts_tool = tool(name="get_topology_hosts")(get_topology_hosts)
get_topology_links_tool = tool(name="get_topology_links")(get_topology_links)
get_host_info_tool = tool(name="get_host_info")(get_host_info)
classify_host_zone_tool = tool(name="classify_host_zone")(classify_host_zone)
choose_default_host_pair_tool = tool(name="choose_default_host_pair")(choose_default_host_pair)
