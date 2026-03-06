import unittest
from pathlib import Path

from sagefuzz_seedgen.schemas import Agent1Output, ObservationIntentSpec, PacketSpec, TaskSpec, UserQuestion
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _apply_initial_intent_answer,
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

    def test_apply_initial_intent_infers_monitoring_family_feature(self) -> None:
        merged = _apply_initial_intent_answer(
            intent_payload={},
            full_intent="测试链路监控功能，验证探测包统计输出。",
            test_objective="control_plane_rules",
        )
        self.assertEqual(merged.get("feature_under_test"), "traffic_monitoring")
        self.assertEqual(merged.get("test_objective"), "control_plane_rules")

    def test_apply_initial_intent_infers_monitoring_family_from_utilization_text(self) -> None:
        merged = _apply_initial_intent_answer(
            intent_payload={},
            full_intent="验证 h1 到 h3 通信路径上一条链路的链路利用率是否能被监控到。",
            test_objective="data_plane_behavior",
        )
        self.assertEqual(merged.get("feature_under_test"), "traffic_monitoring")

    def test_apply_initial_intent_infers_forwarding_family(self) -> None:
        merged = _apply_initial_intent_answer(
            intent_payload={},
            full_intent="验证 IPv4 路由转发是否把流量送到正确下一跳。",
            test_objective="data_plane_behavior",
        )
        self.assertEqual(merged.get("feature_under_test"), "forwarding_behavior")

    def test_task_spec_accepts_observation_requirements(self) -> None:
        task = TaskSpec(
            task_id="t-telemetry",
            task_description="monitor link utilization",
            feature_under_test="traffic_monitoring",
            intent_category="telemetry_monitoring",
            observation_focus="one monitored link on the h1->h3 path",
            expected_observation_semantics="the monitored link metric should increase after traffic",
            observation_requirements=[
                ObservationIntentSpec(
                    order=1,
                    action_type="read_counter",
                    target_hint="monitored_link_counter",
                    timing="after_scenario",
                    purpose="verify monitored link metric after traffic",
                )
            ],
            role_bindings={"sender": "h1", "receiver": "h3"},
        )
        self.assertEqual(task.intent_category, "telemetry_monitoring")
        self.assertEqual(task.observation_requirements[0].action_type, "read_counter")

    def test_user_question_accepts_topology_mapping_alias(self) -> None:
        q = UserQuestion(
            field="topology_mapping",
            question_zh="请描述链路监控相关的主机与路径映射。",
            required=False,
        )
        self.assertEqual(q.field, "topology_mapping")

    def test_fallback_task_spec_accepts_new_intent_categories(self) -> None:
        task = TaskSpec(
            task_id="t-forward",
            task_description="verify forwarding",
            feature_under_test="forwarding_behavior",
            intent_category="forwarding_behavior",
            role_bindings={"host_a": "h1", "host_b": "h3"},
        )
        self.assertEqual(task.intent_category, "forwarding_behavior")

    def test_user_question_accepts_observation_target_field(self) -> None:
        q = UserQuestion(
            field="observation_target",
            question_zh="请说明你希望监控哪一条链路或哪个观测对象。",
            required=True,
        )
        self.assertEqual(q.field, "observation_target")

    def test_task_spec_default_role_bindings_can_be_neutral(self) -> None:
        task = TaskSpec(
            task_id="t-neutral",
            task_description="d",
            feature_under_test="f",
            role_bindings={"host_a": "h1", "host_b": "h3"},
        )
        self.assertIn("host_a", task.role_bindings)
        self.assertIn("host_b", task.role_bindings)


if __name__ == "__main__":
    unittest.main()
