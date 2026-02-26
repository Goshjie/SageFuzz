from __future__ import annotations

from typing import Any, Dict, List

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context


def get_stateful_objects() -> List[Dict[str, Any]]:
    """Return stateful objects (registers/counters/meters) discovered from BMv2 json."""
    ctx = get_program_context()
    out: List[Dict[str, Any]] = []

    for kind in ("register_arrays", "counter_arrays", "meter_arrays"):
        items = ctx.bmv2_json.get(kind, [])
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            rec = {"kind": kind, "name": it.get("name"), "bitwidth": it.get("bitwidth"), "size": it.get("size")}
            out.append(rec)

    return out


get_stateful_objects_tool = tool(name="get_stateful_objects")(get_stateful_objects)
