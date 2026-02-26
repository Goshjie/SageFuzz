from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sagefuzz_seedgen.dot.dot_graph import DotGraph


@dataclass(frozen=True)
class ProgramContext:
    """In-memory, deterministic context loaded at initialization.

    Agents should not receive this as a long prompt. Instead, tools query this context and
    return small, evidence-backed snippets to the model.
    """

    bmv2_json_path: Path
    bmv2_json: Mapping[str, Any]

    graphs_dir: Path
    dot_graphs: Mapping[str, DotGraph]  # name -> graph

    p4info_path: Path
    p4info_txtpb: str

    topology_path: Path
    topology: Mapping[str, Any]

    # Indexes for fast tool queries
    header_types_by_name: Dict[str, Any]
    headers_by_name: Dict[str, Any]
    actions_by_name: Dict[str, Any]
    tables_by_name: Dict[str, Any]

    # Topology-derived indexes
    host_to_switch: Dict[str, str]
    host_info: Dict[str, Dict[str, Any]]

    program_name: Optional[str] = None

