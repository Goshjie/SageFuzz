from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DotNode:
    node_id: str
    label: str
    shape: Optional[str] = None


@dataclass(frozen=True)
class DotEdge:
    src: str
    dst: str
    label: str = ""


class DotGraph:
    """Small, dependency-free DOT graph representation.

    This is used as a fallback when networkx/pydot are not available.
    For our seedgen tools we only need labels, adjacency and basic path queries.
    """

    def __init__(self, *, name: str, nodes: Dict[str, DotNode], edges: List[DotEdge]):
        self.name = name
        self._nodes = nodes
        self._edges = edges
        self._adj: Dict[str, List[DotEdge]] = {}
        for e in edges:
            self._adj.setdefault(e.src, []).append(e)

    def nodes(self) -> Iterable[DotNode]:
        return self._nodes.values()

    def edges(self) -> Iterable[DotEdge]:
        return list(self._edges)

    def get_node(self, node_id: str) -> Optional[DotNode]:
        return self._nodes.get(node_id)

    def find_nodes_by_label(self, label: str) -> List[DotNode]:
        return [n for n in self._nodes.values() if n.label == label]

    def find_node_id_by_label(self, label: str) -> Optional[str]:
        for nid, n in self._nodes.items():
            if n.label == label:
                return nid
        return None

    def out_edges(self, node_id: str) -> List[DotEdge]:
        return list(self._adj.get(node_id, []))

    def get_start_node_id(self) -> Optional[str]:
        return self.find_node_id_by_label("__START__")

    def get_exit_node_id(self) -> Optional[str]:
        return self.find_node_id_by_label("__EXIT__")

    def list_table_labels(self) -> List[str]:
        # In p4c generated DOT, tables are often ellipses.
        out: List[str] = []
        for n in self._nodes.values():
            if (n.shape or "").lower() == "ellipse" and n.label:
                out.append(n.label)
        return out

    def ranked_tables(self) -> List[Tuple[str, int]]:
        """Return (table_label, depth_score) ranked by max distance from __START__.

        Depth is computed as the longest-path distance in a DAG-ish manner. If cycles exist,
        this becomes a bounded DFS with memoization and a recursion guard.
        """

        start = self.get_start_node_id()
        if start is None:
            return []

        memo: Dict[str, int] = {}
        visiting: set[str] = set()

        def dfs(nid: str) -> int:
            if nid in memo:
                return memo[nid]
            if nid in visiting:
                # cycle guard: treat as 0 additional depth
                return 0
            visiting.add(nid)
            best = 0
            for e in self.out_edges(nid):
                best = max(best, 1 + dfs(e.dst))
            visiting.remove(nid)
            memo[nid] = best
            return best

        dfs(start)

        ranked: List[Tuple[str, int]] = []
        for nid, node in self._nodes.items():
            if (node.shape or "").lower() == "ellipse":
                ranked.append((node.label, memo.get(nid, 0)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def path_constraints(self, *, target_label: str, max_paths: int = 3, max_steps: int = 200) -> List[Dict[str, str]]:
        """Extract weak, explainable constraints on paths to a target node.

        Returns a list of {node_label, edge_label} entries along each discovered path.
        This is not a formal solver; it's an evidence helper for agents.
        """

        start = self.get_start_node_id()
        if start is None:
            return []
        target_id = self.find_node_id_by_label(target_label)
        if target_id is None:
            return []

        results: List[List[Dict[str, str]]] = []
        stack: List[Tuple[str, List[Dict[str, str]], int]] = []
        stack.append((start, [], 0))

        while stack and len(results) < max_paths:
            nid, path, steps = stack.pop()
            if steps > max_steps:
                continue
            node = self.get_node(nid)
            if node is None:
                continue

            if nid == target_id:
                results.append(path)
                continue

            for e in reversed(self.out_edges(nid)):
                next_node = self.get_node(e.dst)
                if next_node is None:
                    continue
                # Record constraints primarily at rectangle condition nodes; still keep general labels.
                next_entry = {"node": next_node.label, "via": e.label or ""}
                stack.append((e.dst, path + [next_entry], steps + 1))

        # Flatten to a simplified view: include only likely-constraint nodes (heuristic)
        simplified: List[List[Dict[str, str]]] = []
        for p in results:
            simp: List[Dict[str, str]] = []
            for ent in p:
                lbl = ent["node"]
                if "isValid" in lbl or "==" in lbl or ".hit" in lbl:
                    simp.append(ent)
            simplified.append(simp)

        # If heuristic filters out everything, return raw path for at least one result.
        if simplified and all(len(x) == 0 for x in simplified):
            return results[0]
        return simplified[0] if simplified else []

