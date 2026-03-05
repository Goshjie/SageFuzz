from __future__ import annotations

from typing import Any, Dict, List

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context


def _get_source_text() -> str:
    ctx = get_program_context()
    text = ctx.p4_source_code
    return text if isinstance(text, str) else ""


def get_p4_source_info() -> Dict[str, Any]:
    """Return availability and basic stats for loaded P4 source code."""
    ctx = get_program_context()
    text = _get_source_text()
    lines = text.splitlines() if text else []
    return {
        "available": bool(text),
        "path": str(ctx.p4_source_path) if ctx.p4_source_path else None,
        "line_count": len(lines),
        "char_count": len(text),
        "program_name": ctx.program_name,
    }


def search_p4_source(query: str, max_results: int = 20, case_sensitive: bool = False) -> Dict[str, Any]:
    """Search the loaded P4 source by substring and return matching lines."""
    text = _get_source_text()
    if not isinstance(query, str) or not query.strip() or not text:
        return {
            "query": query,
            "case_sensitive": bool(case_sensitive),
            "available": bool(text),
            "total_matches": 0,
            "truncated": False,
            "matches": [],
        }

    cap = max(1, min(int(max_results), 200))
    needle = query if case_sensitive else query.lower()
    matches: List[Dict[str, Any]] = []
    total = 0
    for idx, line in enumerate(text.splitlines(), 1):
        hay = line if case_sensitive else line.lower()
        if needle in hay:
            total += 1
            if len(matches) < cap:
                matches.append({"line_no": idx, "line": line})

    return {
        "query": query,
        "case_sensitive": bool(case_sensitive),
        "available": True,
        "total_matches": total,
        "truncated": total > len(matches),
        "matches": matches,
    }


def get_p4_source_snippet(start_line: int, end_line: int) -> Dict[str, Any]:
    """Return a bounded P4 source snippet by 1-based line numbers."""
    ctx = get_program_context()
    text = _get_source_text()
    if not text:
        return {
            "available": False,
            "path": str(ctx.p4_source_path) if ctx.p4_source_path else None,
            "start_line": int(start_line),
            "end_line": int(end_line),
            "lines": [],
        }

    lines = text.splitlines()
    total = len(lines)
    start = max(1, int(start_line))
    end = max(start, int(end_line))
    # Keep snippets small and machine-consumable.
    if end - start + 1 > 300:
        end = start + 299
    if start > total:
        selected: List[Dict[str, Any]] = []
        actual_end = min(end, total)
    else:
        actual_end = min(end, total)
        selected = [{"line_no": i, "line": lines[i - 1]} for i in range(start, actual_end + 1)]

    return {
        "available": True,
        "path": str(ctx.p4_source_path) if ctx.p4_source_path else None,
        "start_line": start,
        "end_line": actual_end,
        "lines": selected,
    }


get_p4_source_info_tool = tool(name="get_p4_source_info")(get_p4_source_info)
search_p4_source_tool = tool(name="search_p4_source")(search_p4_source)
get_p4_source_snippet_tool = tool(name="get_p4_source_snippet")(get_p4_source_snippet)

