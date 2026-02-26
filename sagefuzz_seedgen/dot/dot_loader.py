from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sagefuzz_seedgen.dot.dot_graph import DotEdge, DotGraph, DotNode


_NODE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*\[(.+)\]\s*;?\s*$')
_EDGE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*->\s*([A-Za-z0-9_]+)\s*\[(.+)\]\s*;?\s*$')


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_attrs(attr_str: str) -> Dict[str, str]:
    # DOT attribute lists are comma-separated key=value pairs, values often quoted.
    # We only need label/shape; this parser is intentionally small but handles quotes.
    attrs: Dict[str, str] = {}
    cur = ""
    in_quotes = False
    parts: List[str] = []
    for ch in attr_str:
        if ch == '"' and (not cur or cur[-1] != "\\"):
            in_quotes = not in_quotes
        if ch == "," and not in_quotes:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)

    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        attrs[k.strip()] = _strip_quotes(v.strip())
    return attrs


def _load_dot_with_networkx(dot_path: Path) -> Optional[Tuple[Dict[str, DotNode], List[DotEdge]]]:
    try:
        import networkx as nx  # type: ignore
        from networkx.drawing.nx_pydot import read_dot  # type: ignore
    except Exception:
        return None

    g = read_dot(str(dot_path))

    nodes: Dict[str, DotNode] = {}
    for nid, attrs in g.nodes(data=True):
        # attrs values may be lists; normalize to str
        label = attrs.get("label", "")
        if isinstance(label, list) and label:
            label = label[0]
        if not isinstance(label, str):
            label = str(label)
        label = _strip_quotes(label)
        shape = attrs.get("shape")
        if isinstance(shape, list) and shape:
            shape = shape[0]
        shape_str = _strip_quotes(shape) if isinstance(shape, str) else None
        nodes[str(nid)] = DotNode(node_id=str(nid), label=label, shape=shape_str)

    edges: List[DotEdge] = []
    for u, v, attrs in g.edges(data=True):
        label = attrs.get("label", "")
        if isinstance(label, list) and label:
            label = label[0]
        if not isinstance(label, str):
            label = str(label)
        edges.append(DotEdge(src=str(u), dst=str(v), label=_strip_quotes(label)))

    return nodes, edges


def _load_dot_fallback(dot_path: Path) -> Tuple[Dict[str, DotNode], List[DotEdge]]:
    nodes: Dict[str, DotNode] = {}
    edges: List[DotEdge] = []

    for raw in dot_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        # Nodes
        m = _NODE_RE.match(line)
        if m:
            nid, attr_str = m.group(1), m.group(2)
            attrs = _parse_attrs(attr_str)
            label = attrs.get("label", "")
            shape = attrs.get("shape")
            nodes[nid] = DotNode(node_id=nid, label=label, shape=shape)
            continue
        # Edges
        m = _EDGE_RE.match(line)
        if m:
            src, dst, attr_str = m.group(1), m.group(2), m.group(3)
            attrs = _parse_attrs(attr_str)
            edges.append(DotEdge(src=src, dst=dst, label=attrs.get("label", "")))
            continue

    return nodes, edges


def load_dot_graphs(graphs_dir: Path) -> Dict[str, DotGraph]:
    graphs: Dict[str, DotGraph] = {}
    for dot_path in sorted(graphs_dir.glob("*.dot")):
        name = dot_path.stem

        parsed = _load_dot_with_networkx(dot_path)
        if parsed is None:
            nodes, edges = _load_dot_fallback(dot_path)
        else:
            nodes, edges = parsed

        graphs[name] = DotGraph(name=name, nodes=nodes, edges=edges)

    return graphs

