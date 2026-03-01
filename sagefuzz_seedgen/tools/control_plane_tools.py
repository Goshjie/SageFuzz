from __future__ import annotations

from typing import Any, Dict, List

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context


def _normalize_table_key(key: Any) -> Dict[str, Any]:
    if not isinstance(key, dict):
        return {}
    target = key.get("target")
    if isinstance(target, list) and len(target) == 2 and all(isinstance(x, str) for x in target):
        field = f"hdr.{target[0]}.{target[1]}"
    elif isinstance(target, str):
        field = target
    else:
        field = str(target)
    return {"field": field, "match_type": key.get("match_type"), "mask": key.get("mask")}


def get_tables() -> List[Dict[str, Any]]:
    """Return all control-plane tables with key/action signatures."""
    ctx = get_program_context()
    out: List[Dict[str, Any]] = []
    for name in sorted(ctx.tables_by_name.keys()):
        table = ctx.tables_by_name.get(name)
        if not isinstance(table, dict):
            continue
        keys = [_normalize_table_key(k) for k in (table.get("key") or [])]
        actions = [a for a in (table.get("actions") or []) if isinstance(a, str)]
        out.append(
            {
                "name": name,
                "keys": [k for k in keys if k],
                "actions": actions,
                "size": table.get("max_size"),
                "default_action": table.get("default_entry", {}).get("action_id")
                if isinstance(table.get("default_entry"), dict)
                else None,
            }
        )
    return out


def get_table(table_name: str) -> Dict[str, Any]:
    """Return one table's key/action signatures."""
    ctx = get_program_context()
    table = ctx.tables_by_name.get(table_name)
    if not isinstance(table, dict):
        return {"name": table_name, "found": False}
    keys = [_normalize_table_key(k) for k in (table.get("key") or [])]
    actions = [a for a in (table.get("actions") or []) if isinstance(a, str)]
    return {
        "name": table_name,
        "found": True,
        "keys": [k for k in keys if k],
        "actions": actions,
        "size": table.get("max_size"),
        "is_const": table.get("is_const_table"),
    }


def get_action_code(action_name: str) -> Dict[str, Any]:
    """Return action runtime parameter signature and primitive ops."""
    ctx = get_program_context()
    action = ctx.actions_by_name.get(action_name)
    if not isinstance(action, dict):
        return {"name": action_name, "found": False}
    runtime_data = action.get("runtime_data", [])
    params: List[Dict[str, Any]] = []
    if isinstance(runtime_data, list):
        for item in runtime_data:
            if not isinstance(item, dict):
                continue
            params.append({"name": item.get("name"), "bitwidth": item.get("bitwidth")})
    primitives = action.get("primitives", [])
    return {
        "name": action_name,
        "found": True,
        "runtime_data": params,
        "primitives": primitives if isinstance(primitives, list) else [],
    }


get_tables_tool = tool(name="get_tables")(get_tables)
get_table_tool = tool(name="get_table")(get_table)
get_action_code_tool = tool(name="get_action_code")(get_action_code)
