from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.tools import tool

from sagefuzz_seedgen.tools.context_registry import get_program_context


def _normalize_proto_name(h: str) -> str:
    mapping = {"Ethernet": "ethernet", "IPv4": "ipv4", "TCP": "tcp", "UDP": "udp"}
    return mapping.get(h, h).lower()


def _normalize_field_name(header: str, field: str) -> str:
    # Allow some friendly aliases used in prompts/examples.
    if header.lower() == "ipv4" and field in ("proto", "protocol"):
        return "protocol"
    return field


def get_parser_paths() -> List[List[str]]:
    """Return all legal parser protocol stacks, e.g. Ethernet->IPv4->TCP."""
    ctx = get_program_context()
    parsers = ctx.bmv2_json.get("parsers", [])
    if not isinstance(parsers, list) or not parsers:
        return []
    parser0 = parsers[0]
    if not isinstance(parser0, dict):
        return []
    init_state = parser0.get("init_state")
    parse_states = parser0.get("parse_states", [])
    if not isinstance(init_state, str) or not isinstance(parse_states, list):
        return []

    state_by_name: Dict[str, Any] = {st.get("name"): st for st in parse_states if isinstance(st, dict) and st.get("name")}

    def extract_headers(st: Dict[str, Any]) -> List[str]:
        ops = st.get("parser_ops", []) or []
        out: List[str] = []
        if not isinstance(ops, list):
            return out
        for op in ops:
            if not isinstance(op, dict) or op.get("op") != "extract":
                continue
            params = op.get("parameters", [])
            if not isinstance(params, list) or not params:
                continue
            v = params[0].get("value") if isinstance(params[0], dict) else None
            if isinstance(v, str):
                out.append(v)
        return out

    def dfs(state_name: str, stack: List[str], out_paths: List[List[str]], depth: int = 0) -> None:
        if depth > 32:
            return
        st = state_by_name.get(state_name)
        if not isinstance(st, dict):
            return
        stack2 = stack + extract_headers(st)

        transitions = st.get("transitions", []) or []
        if not isinstance(transitions, list) or not transitions:
            # no transitions => accept
            out_paths.append(stack2)
            return

        progressed = False
        for tr in transitions:
            if not isinstance(tr, dict):
                continue
            next_state = tr.get("next_state")
            tr_type = tr.get("type")
            if tr_type == "default" or next_state is None:
                continue
            if isinstance(next_state, str):
                progressed = True
                dfs(next_state, stack2, out_paths, depth + 1)

        if not progressed:
            out_paths.append(stack2)

    raw_paths: List[List[str]] = []
    dfs(init_state, [], raw_paths)

    # Convert header instance names to display names
    display_paths: List[List[str]] = []
    for p in raw_paths:
        dp: List[str] = []
        for inst in p:
            inst_l = inst.lower()
            if inst_l == "ethernet":
                dp.append("Ethernet")
            elif inst_l == "ipv4":
                dp.append("IPv4")
            elif inst_l == "tcp":
                dp.append("TCP")
            elif inst_l == "udp":
                dp.append("UDP")
            else:
                dp.append(inst)
        if dp:
            display_paths.append(dp)
    # Deduplicate
    uniq: List[List[str]] = []
    seen = set()
    for p in display_paths:
        k = tuple(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def get_parser_transitions() -> List[Dict[str, Any]]:
    """Return transition constraints as a list of evidence records.

    Example record: {"field": "Ethernet.etherType", "value": "0x0800", "next_state": "parse_ipv4"}.
    """
    ctx = get_program_context()
    parsers = ctx.bmv2_json.get("parsers", [])
    if not isinstance(parsers, list) or not parsers:
        return []
    parser0 = parsers[0]
    if not isinstance(parser0, dict):
        return []
    parse_states = parser0.get("parse_states", [])
    if not isinstance(parse_states, list):
        return []

    out: List[Dict[str, Any]] = []
    for st in parse_states:
        if not isinstance(st, dict):
            continue
        transition_key = st.get("transition_key", []) or []
        if not isinstance(transition_key, list) or not transition_key:
            continue
        key0 = transition_key[0]
        if not isinstance(key0, dict) or key0.get("type") != "field":
            continue
        fv = key0.get("value")
        if not (isinstance(fv, list) and len(fv) == 2 and isinstance(fv[0], str) and isinstance(fv[1], str)):
            continue
        header_inst, field = fv[0], fv[1]
        header_disp = {"ethernet": "Ethernet", "ipv4": "IPv4", "tcp": "TCP", "udp": "UDP"}.get(
            header_inst.lower(), header_inst
        )
        field_disp = "proto" if (header_disp == "IPv4" and field == "protocol") else field
        full_field = f"{header_disp}.{field_disp}"

        transitions = st.get("transitions", []) or []
        if not isinstance(transitions, list):
            continue
        for tr in transitions:
            if not isinstance(tr, dict):
                continue
            if tr.get("type") == "default":
                continue
            out.append(
                {
                    "state": st.get("name"),
                    "field": full_field,
                    "value": tr.get("value"),
                    "mask": tr.get("mask"),
                    "next_state": tr.get("next_state"),
                }
            )

    return out


def get_header_definitions() -> Dict[str, Dict[str, int]]:
    """Return header instance -> field -> bitwidth."""
    ctx = get_program_context()
    header_types = ctx.header_types_by_name
    headers = ctx.headers_by_name

    out: Dict[str, Dict[str, int]] = {}
    for header_inst, header in headers.items():
        if not isinstance(header, dict):
            continue
        header_type_name = header.get("header_type")
        if not isinstance(header_type_name, str):
            continue
        ht = header_types.get(header_type_name)
        if not isinstance(ht, dict):
            continue
        fields = ht.get("fields", [])
        if not isinstance(fields, list):
            continue
        fdef: Dict[str, int] = {}
        for f in fields:
            # BMv2 json commonly uses ["fieldName", bitwidth, signedFlag]
            if isinstance(f, list) and len(f) >= 2 and isinstance(f[0], str) and isinstance(f[1], int):
                fdef[f[0]] = f[1]
        out[header_inst] = fdef
    return out


def get_header_bits(field_expr: str) -> Optional[int]:
    """Return bitwidth for a field expression like 'Ethernet.etherType' or 'IPv4.proto'."""
    if "." not in field_expr:
        return None
    header, field = field_expr.split(".", 1)
    header = _normalize_proto_name(header)
    field = _normalize_field_name(header, field)

    defs = get_header_definitions()
    header_defs = defs.get(header)
    if not header_defs:
        return None
    bw = header_defs.get(field)
    return int(bw) if isinstance(bw, int) else None


# Agno tool wrappers (Function objects). Keep raw callables for unit tests and deterministic checks.
get_parser_paths_tool = tool(name="get_parser_paths")(get_parser_paths)
get_parser_transitions_tool = tool(name="get_parser_transitions")(get_parser_transitions)
get_header_definitions_tool = tool(name="get_header_definitions")(get_header_definitions)
get_header_bits_tool = tool(name="get_header_bits")(get_header_bits)
