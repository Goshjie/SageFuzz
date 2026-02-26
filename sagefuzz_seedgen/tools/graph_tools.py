from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context


def _get_graph(graph_name: str):
    ctx = get_program_context()
    g = ctx.dot_graphs.get(graph_name)
    if g is None:
        # Try common fallback names.
        for cand in ("MyIngress", "Ingress", "ingress"):
            g = ctx.dot_graphs.get(cand)
            if g is not None:
                break
    return g


def get_jump_dict(graph_name: str = "MyIngress") -> Dict[str, List[Dict[str, Any]]]:
    """Return a label-level jump dictionary: src_label -> [{via, dst}, ...]."""
    g = _get_graph(graph_name)
    if g is None:
        return {}

    out: Dict[str, List[Dict[str, Any]]] = {}
    for e in g.edges():
        src = g.get_node(e.src)
        dst = g.get_node(e.dst)
        if src is None or dst is None:
            continue
        out.setdefault(src.label, []).append({"via": e.label or "", "dst": dst.label})
    return out


def get_ranked_tables(graph_name: str = "MyIngress") -> List[Dict[str, Any]]:
    """Return table labels ranked by (heuristic) depth."""
    g = _get_graph(graph_name)
    if g is None:
        return []
    ranked = g.ranked_tables()
    return [{"table": t, "depth": d} for t, d in ranked]


def get_path_constraints(target: str, graph_name: str = "MyIngress") -> List[Dict[str, str]]:
    """Return weak/evidence path constraints to reach a target label in the control graph."""
    g = _get_graph(graph_name)
    if g is None:
        return []
    return g.path_constraints(target_label=target)


get_jump_dict_tool = tool(name="get_jump_dict")(get_jump_dict)
get_ranked_tables_tool = tool(name="get_ranked_tables")(get_ranked_tables)
get_path_constraints_tool = tool(name="get_path_constraints")(get_path_constraints)
