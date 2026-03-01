from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from json_repair import repair_json

TOOL_ARGUMENT_ALIASES: Dict[str, Dict[str, str]] = {
    "get_host_info": {"user_id": "host_id", "id": "host_id", "host": "host_id"},
    "classify_host_zone": {"user_id": "host_id", "id": "host_id", "host": "host_id"},
    "get_header_bits": {"field": "field_expr", "header_field": "field_expr"},
    "get_path_constraints": {"target_label": "target", "label": "target"},
    "get_table": {"table": "table_name", "name": "table_name"},
    "get_action_code": {"action": "action_name", "name": "action_name"},
    "get_ranked_tables": {"graph": "graph_name"},
    "get_jump_dict": {"graph": "graph_name"},
}


def _get_function_schema(function_obj: Any) -> Dict[str, Any]:
    schema = getattr(function_obj, "parameters", None)
    return schema if isinstance(schema, dict) else {}


def _has_no_parameters(function_obj: Any) -> bool:
    schema = _get_function_schema(function_obj)
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict):
        return False
    if len(properties) != 0:
        return False
    return not required


def _get_required_fields(function_obj: Any) -> List[str]:
    schema = _get_function_schema(function_obj)
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [name for name in required if isinstance(name, str)]


def _is_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _get_properties(function_obj: Any) -> Dict[str, Any]:
    schema = _get_function_schema(function_obj)
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _coerce_by_json_schema(value: Any, schema: Dict[str, Any]) -> Any:
    type_name = schema.get("type")

    if not isinstance(type_name, str):
        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            for candidate in any_of:
                if not isinstance(candidate, dict):
                    continue
                coerced = _coerce_by_json_schema(value, candidate)
                if _matches_json_type(coerced, candidate.get("type")):
                    return coerced
        return value

    if type_name == "string":
        if value is None:
            return value
        return value if isinstance(value, str) else str(value)

    if type_name == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if raw == "":
                return value
            try:
                return int(raw, 10)
            except Exception:
                return value
        return value

    if type_name == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if raw == "":
                return value
            try:
                return float(raw)
            except Exception:
                return value
        return value

    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw in {"true", "1", "yes", "y", "是"}:
                return True
            if raw in {"false", "0", "no", "n", "否"}:
                return False
        return value

    return value


def _matches_json_type(value: Any, type_name: Any) -> bool:
    if not isinstance(type_name, str):
        return True
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return True


def _sanitize_arguments_for_function(name: str, args: Dict[str, Any], function_obj: Any) -> Optional[Dict[str, Any]]:
    properties = _get_properties(function_obj)
    required = _get_required_fields(function_obj)

    # No-arg tools: normalize everything to an empty object.
    if len(properties) == 0 and not required:
        return {}

    cleaned: Dict[str, Any] = dict(args)

    aliases = TOOL_ARGUMENT_ALIASES.get(name, {})
    for alias, canonical in aliases.items():
        if alias in cleaned and canonical not in cleaned:
            cleaned[canonical] = cleaned[alias]

    # Heuristic fallback: if exactly one required field is missing and there is exactly one unknown key,
    # map unknown key's value to the missing required field.
    missing_required = [field for field in required if not _is_non_empty_value(cleaned.get(field))]
    unknown_keys = [key for key in cleaned.keys() if key not in properties]
    if len(missing_required) == 1 and len(unknown_keys) == 1:
        cleaned[missing_required[0]] = cleaned[unknown_keys[0]]

    # Keep only declared properties.
    cleaned = {key: value for key, value in cleaned.items() if key in properties}

    # Coerce by property schema.
    for key, value in list(cleaned.items()):
        schema = properties.get(key)
        if isinstance(schema, dict):
            cleaned[key] = _coerce_by_json_schema(value, schema)

    # Final required-field gate.
    if any(not _is_non_empty_value(cleaned.get(field)) for field in required):
        return None

    return cleaned


def _repair_tool_arguments(
    *,
    name: str,
    arguments: Optional[str],
    functions: Optional[Dict[str, Any]],
) -> Optional[str]:
    if arguments is None:
        return None

    raw = arguments.strip()
    if raw == "":
        return arguments

    target_func = functions.get(name) if isinstance(functions, dict) else None
    no_parameters = target_func is not None and _has_no_parameters(target_func)

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return "{}" if no_parameters else arguments
        if target_func is None:
            return json.dumps(parsed, ensure_ascii=False)
        sanitized = _sanitize_arguments_for_function(name, parsed, target_func)
        if sanitized is None:
            return arguments
        return json.dumps(sanitized, ensure_ascii=False)
    except Exception:
        pass

    try:
        repaired_obj = repair_json(raw, return_objects=True)
    except Exception:
        repaired_obj = None

    if no_parameters:
        # For no-argument tools, always normalize malformed args to an empty object.
        return "{}"

    if not isinstance(repaired_obj, dict):
        return arguments

    if target_func is not None:
        sanitized = _sanitize_arguments_for_function(name, repaired_obj, target_func)
        if sanitized is None:
            # Keep the original malformed payload so Agno can trigger a retry with guidance.
            return arguments
        return json.dumps(sanitized, ensure_ascii=False)

    return json.dumps(repaired_obj, ensure_ascii=False)


def install_agno_argument_patch() -> None:
    """Install a lightweight monkey patch for malformed tool-call argument strings.

    This keeps behavior unchanged for valid payloads, while using json-repair
    for malformed argument payloads from OpenAI-like providers.
    """

    try:
        from agno.utils import functions as functions_mod
        from agno.utils import tools as tools_mod
    except Exception:
        return

    if getattr(functions_mod, "_sagefuzz_arg_patch_installed", False):
        return

    original_get_function_call = functions_mod.get_function_call

    def patched_get_function_call(
        name: str,
        arguments: Optional[str] = None,
        call_id: Optional[str] = None,
        functions: Optional[Dict[str, Any]] = None,
    ):
        repaired_args = _repair_tool_arguments(name=name, arguments=arguments, functions=functions)
        return original_get_function_call(
            name=name,
            arguments=repaired_args,
            call_id=call_id,
            functions=functions,
        )

    functions_mod.get_function_call = patched_get_function_call
    tools_mod.get_function_call = patched_get_function_call
    functions_mod._sagefuzz_arg_patch_installed = True
