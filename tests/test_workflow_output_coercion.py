import unittest
from pathlib import Path

from sagefuzz_seedgen.schemas import Agent1Output, PacketSpec, TaskSpec
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _coerce_schema_output,
    _group_packets_by_scenario,
    _normalize_test_objective,
    _resolve_generation_mode,
    _resolve_output_paths,
    _split_case_records_by_kind,
)


class TestWorkflowOutputCoercion(unittest.TestCase):
    def test_coerce_dict_to_schema(self) -> None:
        raw = {"kind": "questions", "questions": []}
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")

    def test_coerce_json_string_to_schema(self) -> None:
        raw = '{"kind":"questions","questions":[]}'
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")

    def test_invalid_string_returns_none(self) -> None:
        out = _coerce_schema_output("not json", Agent1Output)
        self.assertIsNone(out)

    def test_mixed_string_extracts_json_object(self) -> None:
        raw = 'prefix text {"kind":"questions","questions":[]} trailing'
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")

    def test_group_packets_by_scenario(self) -> None:
        packets = [
            PacketSpec(packet_id=1, tx_host="h1", scenario="positive_main", protocol_stack=["Ethernet"], fields={}),
            PacketSpec(packet_id=2, tx_host="h3", scenario="negative_probe", protocol_stack=["Ethernet"], fields={}),
            PacketSpec(packet_id=3, tx_host="h1", scenario=None, protocol_stack=["Ethernet"], fields={}),
        ]
        grouped = _group_packets_by_scenario(packets)
        self.assertEqual(len(grouped["positive_main"]), 1)
        self.assertEqual(len(grouped["negative_probe"]), 1)
        self.assertEqual(len(grouped["default"]), 1)

    def test_resolve_output_paths_defaults(self) -> None:
        index, cases = _resolve_output_paths("run123", None)
        self.assertEqual(index, Path("runs/run123_packet_sequence_index.json"))
        self.assertEqual(cases, Path("runs/run123_testcases"))

    def test_split_case_records_by_kind(self) -> None:
        grouped = _split_case_records_by_kind(
            [
                {"scenario": "positive_main", "kind": "positive"},
                {"scenario": "negative_probe", "kind": "negative"},
                {"scenario": "unknown_case", "kind": "other"},
            ]
        )
        self.assertEqual(len(grouped["positive"]), 1)
        self.assertEqual(len(grouped["negative"]), 1)
        self.assertEqual(len(grouped["neutral"]), 1)

    def test_normalize_test_objective(self) -> None:
        self.assertEqual(_normalize_test_objective("1"), "data_plane_behavior")
        self.assertEqual(_normalize_test_objective("控制平面规则"), "control_plane_rules")
        self.assertEqual(_normalize_test_objective("dp"), "data_plane_behavior")
        self.assertIsNone(_normalize_test_objective("unknown-token"))

    def test_resolve_generation_mode(self) -> None:
        task = TaskSpec(task_id="t1", task_description="d", feature_under_test="f", role_bindings={})
        self.assertEqual(
            _resolve_generation_mode(intent_payload={"test_objective": "2"}, task=task),
            "packet_only",
        )
        self.assertEqual(
            _resolve_generation_mode(intent_payload={"test_objective": "数据平面行为"}, task=task),
            "packet_and_entities",
        )
        task_packet_only = task.model_copy(update={"generation_mode": "packet_only"})
        self.assertEqual(
            _resolve_generation_mode(intent_payload={}, task=task_packet_only),
            "packet_only",
        )


if __name__ == "__main__":
    unittest.main()
