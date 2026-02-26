from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

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


def _build_topology_indexes(topology: Mapping[str, Any]) -> tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    # host_id -> switch_id, derived from links like ["h1","s1-p1"]
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

    return host_to_switch, host_info


def initialize_program_context(
    *,
    bmv2_json_path: Path,
    graphs_dir: Path,
    p4info_path: Path,
    topology_path: Path,
) -> ProgramContext:
    bmv2_json_path = bmv2_json_path.resolve()
    graphs_dir = graphs_dir.resolve()
    p4info_path = p4info_path.resolve()
    topology_path = topology_path.resolve()

    with bmv2_json_path.open("r", encoding="utf-8") as f:
        bmv2_json = json.load(f)

    dot_graphs = load_dot_graphs(graphs_dir)

    with p4info_path.open("r", encoding="utf-8") as f:
        p4info_txtpb = f.read()

    with topology_path.open("r", encoding="utf-8") as f:
        topology = json.load(f)

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

