from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sagefuzz_seedgen.dot.dot_loader import load_dot_graphs
from sagefuzz_seedgen.runtime.program_context import ProgramContext


def _index_by_name(items: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("name"), str):
            out[it["name"]] = it
    return out


def _index_tables(bmv2_json: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    pipelines = bmv2_json.get("pipelines", [])
    if not isinstance(pipelines, list):
        return out
    for pipe in pipelines:
        if not isinstance(pipe, dict):
            continue
        for table in pipe.get("tables", []) or []:
            if isinstance(table, dict) and isinstance(table.get("name"), str):
                out[table["name"]] = table
    return out


def _node_link_to_topology(raw: Mapping[str, Any]) -> Dict[str, Any]:
    hosts: Dict[str, Dict[str, Any]] = {}
    links: list[list[str]] = []

    nodes = raw.get("nodes", [])
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str):
                continue
            if bool(node.get("isHost")) or node_id.startswith("h"):
                hosts[node_id] = {
                    "ip": node.get("ip"),
                    "mac": node.get("mac"),
                    "defaultRoute": node.get("defaultRoute"),
                    "commands": node.get("commands"),
                }

    raw_links = raw.get("links", [])
    if isinstance(raw_links, list):
        for link in raw_links:
            if not isinstance(link, dict):
                continue
            a = link.get("node1") or link.get("source")
            b = link.get("node2") or link.get("target")
            if not isinstance(a, str) or not isinstance(b, str):
                continue
            port1 = link.get("port1")
            port2 = link.get("port2")
            end_a = f"{a}-p{port1}" if isinstance(port1, int) and a.startswith("s") else a
            end_b = f"{b}-p{port2}" if isinstance(port2, int) and b.startswith("s") else b
            links.append([end_a, end_b])

    return {"hosts": hosts, "links": links}


def _infer_host_info_from_assignment(
    host_id: str,
    switch_id: str,
    *,
    assignment_strategy: Optional[str],
) -> Dict[str, Any]:
    try:
        host_num = int(host_id.lstrip("h"))
    except Exception:
        return {}
    try:
        switch_num = int(switch_id.lstrip("s"))
    except Exception:
        switch_num = host_num

    strategy = (assignment_strategy or "").strip().lower()
    if strategy == "l3":
        ip = f"10.{switch_num}.{host_num}.2/24"
    else:
        ip = f"10.0.{host_num}.2/24"
    mac = f"00:00:0a:{(switch_num if strategy == 'l3' else 0):02x}:{host_num:02x}:02"
    return {"ip": ip, "mac": mac}


def _normalize_p4app_topology(topology: Mapping[str, Any]) -> Dict[str, Any]:
    hosts_out: Dict[str, Dict[str, Any]] = {}
    links_out: list[list[str]] = []

    links = topology.get("links", [])
    host_to_switch: Dict[str, str] = {}
    if isinstance(links, list):
        for link in links:
            if not (isinstance(link, list) and len(link) >= 2):
                continue
            a = link[0]
            b = link[1]
            if isinstance(a, str) and isinstance(b, str):
                if a.startswith("h") and b.startswith("s"):
                    host_to_switch[a] = b
                    links_out.append([a, f"{b}-p1"])
                elif b.startswith("h") and a.startswith("s"):
                    host_to_switch[b] = a
                    links_out.append([f"{a}-p1", b])
                else:
                    links_out.append([a, b])

    hosts = topology.get("hosts", {})
    assignment_strategy = topology.get("assignment_strategy")
    if isinstance(hosts, dict):
        for hid, info in hosts.items():
            if not isinstance(hid, str):
                continue
            base = dict(info) if isinstance(info, dict) else {}
            if hid not in base or not base.get("ip") or not base.get("mac"):
                inferred = _infer_host_info_from_assignment(
                    hid,
                    host_to_switch.get(hid, f"s{hid.lstrip('h') or '1'}"),
                    assignment_strategy=assignment_strategy if isinstance(assignment_strategy, str) else None,
                )
                base.setdefault("ip", inferred.get("ip"))
                base.setdefault("mac", inferred.get("mac"))
            hosts_out[hid] = base

    return {"hosts": hosts_out, "links": links_out}


def _normalize_topology(raw: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(raw.get("hosts"), dict) and isinstance(raw.get("links"), list):
        return {"hosts": dict(raw.get("hosts", {})), "links": list(raw.get("links", []))}

    topology = raw.get("topology")
    if isinstance(topology, dict):
        if isinstance(topology.get("hosts"), dict) and isinstance(topology.get("links"), list):
            return _normalize_p4app_topology(topology)

    if isinstance(raw.get("nodes"), list) and isinstance(raw.get("links"), list):
        return _node_link_to_topology(raw)

    return {"hosts": {}, "links": []}


def _build_topology_indexes(topology: Mapping[str, Any]) -> tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    host_to_switch: Dict[str, str] = {}
    host_info: Dict[str, Dict[str, Any]] = {}

    hosts = topology.get("hosts", {})
    if isinstance(hosts, dict):
        for hid, info in hosts.items():
            if isinstance(hid, str) and isinstance(info, dict):
                host_info[hid] = dict(info)

    links = topology.get("links", [])
    if isinstance(links, list):
        for link in links:
            if not (isinstance(link, list) and len(link) == 2):
                continue
            a, b = link
            if isinstance(a, str) and isinstance(b, str):
                if a.startswith("h") and "-p" in b:
                    host_to_switch[a] = b.split("-p", 1)[0]
                elif b.startswith("h") and "-p" in a:
                    host_to_switch[b] = a.split("-p", 1)[0]
                elif a.startswith("h") and b.startswith("s"):
                    host_to_switch[a] = b
                elif b.startswith("h") and a.startswith("s"):
                    host_to_switch[b] = a

    return host_to_switch, host_info


def initialize_program_context(
    *,
    bmv2_json_path: Path,
    graphs_dir: Path,
    p4info_path: Path,
    topology_path: Path,
    p4_source_path: Optional[Path] = None,
) -> ProgramContext:
    bmv2_json_path = bmv2_json_path.resolve()
    graphs_dir = graphs_dir.resolve()
    p4info_path = p4info_path.resolve()
    topology_path = topology_path.resolve()
    resolved_p4_source_path: Optional[Path] = None
    p4_source_code: Optional[str] = None
    if p4_source_path is not None:
        resolved_p4_source_path = p4_source_path.resolve()
        with resolved_p4_source_path.open("r", encoding="utf-8") as f:
            p4_source_code = f.read()

    with bmv2_json_path.open("r", encoding="utf-8") as f:
        bmv2_json = json.load(f)

    dot_graphs = load_dot_graphs(graphs_dir)

    with p4info_path.open("r", encoding="utf-8") as f:
        p4info_txtpb = f.read()

    with topology_path.open("r", encoding="utf-8") as f:
        raw_topology = json.load(f)
    topology = _normalize_topology(raw_topology)

    header_types_by_name = _index_by_name(bmv2_json.get("header_types"))
    headers_by_name = _index_by_name(bmv2_json.get("headers"))
    actions_by_name = _index_by_name(bmv2_json.get("actions"))
    tables_by_name = _index_tables(bmv2_json)

    host_to_switch, host_info = _build_topology_indexes(topology)

    program_name = bmv2_json.get("program")
    if not isinstance(program_name, str):
        program_name = None

    return ProgramContext(
        bmv2_json_path=bmv2_json_path,
        bmv2_json=bmv2_json,
        graphs_dir=graphs_dir,
        dot_graphs=dot_graphs,
        p4info_path=p4info_path,
        p4info_txtpb=p4info_txtpb,
        p4_source_path=resolved_p4_source_path,
        p4_source_code=p4_source_code,
        topology_path=topology_path,
        topology=topology,
        header_types_by_name=header_types_by_name,
        headers_by_name=headers_by_name,
        actions_by_name=actions_by_name,
        tables_by_name=tables_by_name,
        host_to_switch=host_to_switch,
        host_info=host_info,
        program_name=program_name,
    )
