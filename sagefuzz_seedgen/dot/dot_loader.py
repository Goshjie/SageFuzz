from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from sagefuzz_seedgen.dot.dot_graph import DotEdge, DotGraph, DotNode


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _require_networkx() -> None:
    try:
        import networkx  # noqa: F401
        import pydot  # noqa: F401
    except Exception as e:
        raise RuntimeError(
            "DOT loading requires networkx + pydot. Please install dependencies (e.g. `pip install -r requirements.txt`)."
        ) from e


def load_dot_graphs(graphs_dir: Path) -> Dict[str, DotGraph]:
    """Load DOT graphs using NetworkX (hard dependency).

    This implementation intentionally fails fast if networkx/pydot are missing, to match
    the design requirement: DOT must be loaded via NetworkX into memory for tool queries.
    """

    _require_networkx()
    import networkx as nx  # type: ignore
    import pydot  # type: ignore

    graphs: Dict[str, DotGraph] = {}
    for dot_path in sorted(graphs_dir.glob("*.dot")):
        name = dot_path.stem
        parsed = pydot.graph_from_dot_file(str(dot_path))
        if not parsed:
            raise RuntimeError(f"Failed to parse DOT file: {dot_path}")
        pd_graph = parsed[0]

        # p4c-generated graphs often put actual nodes/edges inside subgraphs (cluster).
        # Collect recursively to ensure we don't miss them.
        pd_nodes = []
        pd_edges = []

        def collect(g) -> None:
            pd_nodes.extend(g.get_nodes() or [])
            pd_edges.extend(g.get_edges() or [])
            for sg in g.get_subgraphs() or []:
                collect(sg)

        collect(pd_graph)

        nx_graph = nx.MultiDiGraph(name=name)
        nodes: Dict[str, DotNode] = {}
        for n in pd_nodes:
            nid = n.get_name()
            attrs = n.get_attributes() or {}
            label = _strip_quotes(str(attrs.get("label", "")))
            shape = attrs.get("shape")
            shape_str = _strip_quotes(shape) if isinstance(shape, str) else None
            # Skip the special "graph" pseudo-node used for subgraph attributes.
            if nid == "graph":
                continue
            nid = _strip_quotes(str(nid))
            nodes[nid] = DotNode(node_id=nid, label=label, shape=shape_str)
            nx_graph.add_node(nid, **attrs)

        edges: List[DotEdge] = []
        for e in pd_edges:
            src = _strip_quotes(str(e.get_source()))
            dst = _strip_quotes(str(e.get_destination()))
            attrs = e.get_attributes() or {}
            lbl = _strip_quotes(str(attrs.get("label", "")))
            edges.append(DotEdge(src=src, dst=dst, label=lbl))
            nx_graph.add_edge(src, dst, **attrs)

        graphs[name] = DotGraph(name=name, nodes=nodes, edges=edges, nx_graph=nx_graph)

    return graphs
