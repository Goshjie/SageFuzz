import unittest
import json

from sagefuzz_seedgen.runtime.agno_patches import (
    _repair_tool_arguments,
    _resolve_tool_name,
)


class _DummyFunction:
    def __init__(self, parameters):
        self.parameters = parameters


class TestAgnoArgumentPatch(unittest.TestCase):
    def test_keep_valid_json_arguments(self) -> None:
        out = _repair_tool_arguments(
            name="get_topology_hosts",
            arguments='{"host_id":"h1"}',
            functions={},
        )
        self.assertEqual(json.loads(out), {"host_id": "h1"})

    def test_repair_single_open_brace_for_no_arg_tool(self) -> None:
        out = _repair_tool_arguments(
            name="get_parser_paths",
            arguments="{",
            functions={
                "get_parser_paths": _DummyFunction(
                    {"type": "object", "properties": {}, "required": []}
                )
            },
        )
        self.assertEqual(out, "{}")

    def test_fallback_to_empty_object_for_malformed_no_arg_tool(self) -> None:
        out = _repair_tool_arguments(
            name="get_parser_paths",
            arguments='{"foo":',
            functions={
                "get_parser_paths": _DummyFunction(
                    {"type": "object", "properties": {}, "required": []}
                )
            },
        )
        self.assertEqual(out, "{}")

    def test_do_not_overwrite_required_arguments(self) -> None:
        raw = '{"host_id":'
        out = _repair_tool_arguments(
            name="get_host_info",
            arguments=raw,
            functions={
                "get_host_info": _DummyFunction(
                    {"type": "object", "properties": {"host_id": {"type": "string"}}, "required": ["host_id"]}
                )
            },
        )
        self.assertEqual(out, raw)

    def test_alias_is_normalized_for_host_tools(self) -> None:
        out = _repair_tool_arguments(
            name="classify_host_zone",
            arguments='{"user_id":"h3"}',
            functions={
                "classify_host_zone": _DummyFunction(
                    {"type": "object", "properties": {"host_id": {"type": "string"}}, "required": ["host_id"]}
                )
            },
        )
        self.assertEqual(json.loads(out), {"host_id": "h3"})

    def test_unknown_key_maps_to_single_required_field(self) -> None:
        out = _repair_tool_arguments(
            name="get_table",
            arguments='{"table":"MyIngress.ipv4_lpm"}',
            functions={
                "get_table": _DummyFunction(
                    {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]}
                )
            },
        )
        self.assertEqual(json.loads(out), {"table_name": "MyIngress.ipv4_lpm"})

    def test_value_type_is_coerced_by_schema(self) -> None:
        out = _repair_tool_arguments(
            name="demo",
            arguments='{"port":"3"}',
            functions={
                "demo": _DummyFunction(
                    {"type": "object", "properties": {"port": {"type": "integer"}}, "required": ["port"]}
                )
            },
        )
        self.assertEqual(json.loads(out), {"port": 3})

    def test_resolve_tool_name_from_camel_case_alias(self) -> None:
        resolved = _resolve_tool_name(
            name="get_hostInfo",
            functions={"get_host_info": _DummyFunction({"type": "object", "properties": {}, "required": []})},
        )
        self.assertEqual(resolved, "get_host_info")

    def test_resolve_tool_name_by_relaxed_lookup(self) -> None:
        resolved = _resolve_tool_name(
            name="getTopologyHosts",
            functions={"get_topology_hosts": _DummyFunction({"type": "object", "properties": {}, "required": []})},
        )
        self.assertEqual(resolved, "get_topology_hosts")

    def test_resolve_tool_name_keeps_unknown_name(self) -> None:
        resolved = _resolve_tool_name(
            name="non_existing_tool",
            functions={"get_topology_hosts": _DummyFunction({"type": "object", "properties": {}, "required": []})},
        )
        self.assertEqual(resolved, "non_existing_tool")


if __name__ == "__main__":
    unittest.main()
