import unittest
from pathlib import Path
from types import SimpleNamespace

from sagefuzz_seedgen.schemas import Agent1Output, ObservationIntentSpec, OperatorActionSpec, PacketSpec, TaskSpec, UserQuestion
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _apply_initial_intent_answer,
    _apply_load_distribution_fallback,
    _apply_operator_action_fallback,
    _apply_telemetry_monitoring_fallback,
    _coerce_schema_output,
    _group_packets_by_scenario,
    _materialize_expected_packet_value,
    _normalize_task_with_intent_fallback,
    _normalize_test_objective,
    _resolve_generation_mode,
    _resolve_output_paths,
    _synthesize_task_from_intent,
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
        telemetry_task = TaskSpec(
            task_id="t-telemetry-mode",
            task_description="monitor",
            feature_under_test="traffic_monitoring",
            intent_category="telemetry_monitoring",
            role_bindings={"host_a": "h1", "host_b": "h3"},
        )
        self.assertEqual(
            _resolve_generation_mode(intent_payload={"test_objective": "数据平面行为"}, task=telemetry_task),
            "packet_only",
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

    def test_task_spec_accepts_operator_actions(self) -> None:
        task = TaskSpec(
            task_id="t-op",
            task_description="manual threshold setup",
            feature_under_test="heavy_hitter_detection",
            intent_category="stateful_policy",
            operator_actions=[
                OperatorActionSpec(
                    order=1,
                    action_type="manual_threshold_override",
                    timing="before_traffic",
                    target="PACKET_THRESHOLD",
                    parameters={"new_value": 10},
                    expected_effect="threshold lowered before traffic",
                )
            ],
            role_bindings={"sender": "h1", "receiver": "h2"},
        )
        self.assertEqual(task.operator_actions[0].action_type, "manual_threshold_override")

    def test_user_question_accepts_topology_mapping_alias(self) -> None:
        q = UserQuestion(
            field="topology_mapping",
            question_zh="请描述链路监控相关的主机与路径映射。",
            required=False,
        )
        self.assertEqual(q.field, "topology_mapping")

    def test_operator_action_fallback_infers_link_failure_and_notify(self) -> None:
        task = TaskSpec(
            task_id="fr1",
            task_description="reroute after s1-s2 link failure and controller reconvergence",
            feature_under_test="forwarding_behavior",
            intent_category="path_validation",
            role_bindings={"traffic_src": "h2", "traffic_dst": "h4"},
        )
        patched = _apply_operator_action_fallback(
            intent_payload={
                "intent_text": "人工将 s1-s2 链路断开，然后通知控制器重收敛。",
            },
            task=task,
        )
        self.assertEqual(len(patched.operator_actions), 2)
        self.assertEqual(patched.operator_actions[0].action_type, "manual_link_event")
        self.assertEqual(patched.operator_actions[1].action_type, "manual_controller_notify")

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

    def test_materialize_expected_packet_value_handles_one_of_dict(self) -> None:
        task = TaskSpec(
            task_id="t-flags",
            task_description="d",
            feature_under_test="f",
            role_bindings={"initiator": "h1", "responder": "h2"},
        )
        ctx = SimpleNamespace(host_info={"h1": {"ip": "10.0.0.1/24", "mac": "00:00:00:00:00:01"}, "h2": {"ip": "10.0.0.2/24", "mac": "00:00:00:00:00:02"}})
        value = _materialize_expected_packet_value(
            field_name="TCP.flags",
            expected={"one_of": ["0x02", 2, "SYN"]},
            ctx=ctx,
            task=task,
            tx_host="h1",
            rx_host="h2",
            packet_id=1,
            step_index=1,
        )
        self.assertEqual(value, "0x02")

    def test_materialize_expected_packet_value_keeps_fixed_congest_flow_constant(self) -> None:
        task = TaskSpec(
            task_id="t-heavy",
            task_description="d",
            feature_under_test="f",
            role_bindings={"initiator": "h1", "responder": "h2"},
        )
        ctx = SimpleNamespace(host_info={"h1": {}, "h2": {}})
        v1 = _materialize_expected_packet_value(
            field_name="TCP.sport",
            expected="fixed_to_congest_flow",
            ctx=ctx,
            task=task,
            tx_host="h1",
            rx_host="h2",
            packet_id=1,
            step_index=1,
        )
        v2 = _materialize_expected_packet_value(
            field_name="TCP.sport",
            expected="fixed_to_congest_flow",
            ctx=ctx,
            task=task,
            tx_host="h1",
            rx_host="h2",
            packet_id=2,
            step_index=2,
        )
        self.assertEqual(v1, 12000)
        self.assertEqual(v2, 12000)

    def test_apply_telemetry_monitoring_fallback_forces_packet_only(self) -> None:
        task = TaskSpec.model_validate(
            {
                "task_id": "telemetry-task",
                "task_description": "monitor link utilization",
                "feature_under_test": "traffic_monitoring",
                "intent_category": "telemetry_monitoring",
                "role_bindings": {"initiator": "h1", "responder": "h3"},
                "generation_mode": "packet_and_entities",
                "require_positive_and_negative": False,
                "sequence_contract": [
                    {
                        "scenario": "positive",
                        "kind": "positive",
                        "required": True,
                        "allow_additional_packets": False,
                        "steps": [
                            {
                                "tx_role": "initiator",
                                "rx_role": "responder",
                                "protocol_stack": ["Ethernet", "probe"],
                            }
                        ],
                    }
                ],
            }
        )
        ctx = SimpleNamespace(
            topology={"links": [["s1", "s2"]]},
            headers_by_name={"probe": {}, "probe_fwd": {}},
        )
        patched = _apply_telemetry_monitoring_fallback(ctx=ctx, intent_payload={"intent_text": "probe monitor"}, task=task)
        self.assertEqual(patched.generation_mode, "packet_only")
        self.assertEqual(patched.sequence_contract[0].steps[-1].protocol_stack, ["Ethernet", "probe", "probe_fwd"])

    def test_apply_load_distribution_fallback_adds_multi_flow_hints(self) -> None:
        task = TaskSpec.model_validate(
            {
                "task_id": "lb-task",
                "task_description": "load balancing",
                "feature_under_test": "forwarding_behavior",
                "intent_category": "load_distribution",
                "role_bindings": {"initiator": "h1", "responder": "h5"},
                "require_positive_and_negative": False,
                "sequence_contract": [
                    {
                        "scenario": "baseline_load_distribution",
                        "kind": "positive",
                        "required": True,
                        "allow_additional_packets": False,
                        "steps": [
                            {
                                "tx_role": "initiator",
                                "rx_role": "responder",
                                "protocol_stack": ["Ethernet", "IPv4", "TCP"],
                            }
                        ],
                    },
                    {
                        "scenario": "congestion_induced_failover",
                        "kind": "positive",
                        "required": True,
                        "allow_additional_packets": False,
                        "steps": [
                            {
                                "tx_role": "initiator",
                                "rx_role": "responder",
                                "protocol_stack": ["Ethernet", "IPv4", "TCP"],
                            }
                        ],
                    },
                ],
            }
        )
        patched = _apply_load_distribution_fallback(intent_payload={"intent_text": "load balancing with congestion"}, task=task)
        self.assertEqual(patched.sequence_contract[0].steps[0].field_expectations["TCP.sport"], "flow_hash_baseline")
        self.assertEqual(patched.sequence_contract[1].steps[0].field_expectations["TCP.sport"], "new_flow_different_hash")

    def test_synthesize_task_from_intent_builds_heavy_hitter_contract(self) -> None:
        ctx = SimpleNamespace(
            host_info={"h1": {}, "h2": {}, "h3": {}},
            headers_by_name={},
        )
        task = _synthesize_task_from_intent(
            ctx=ctx,
            intent_payload={"intent_text": "验证 heavy hitter 检测功能，让 h1 向 h2 发送同一条五元组 TCP 流并在阈值后丢弃。"},
        )
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.intent_category, "stateful_policy")
        self.assertEqual(task.sequence_contract[1].kind, "negative")

    def test_normalize_task_with_intent_fallback_replaces_incomplete_heavy_hitter_task(self) -> None:
        ctx = SimpleNamespace(
            host_info={"h1": {}, "h2": {}, "h3": {}},
            headers_by_name={},
        )
        original = TaskSpec.model_validate(
            {
                "task_id": "hh-original",
                "task_description": "heavy hitter task",
                "feature_under_test": "forwarding_behavior",
                "intent_category": "forwarding_behavior",
                "role_bindings": {"initiator": "h1", "responder": "h2"},
                "require_positive_and_negative": True,
                "sequence_contract": [
                    {
                        "scenario": "positive_only",
                        "kind": "positive",
                        "required": True,
                        "allow_additional_packets": False,
                        "steps": [
                            {
                                "tx_role": "initiator",
                                "rx_role": "responder",
                                "protocol_stack": ["Ethernet", "IPv4", "TCP"],
                            }
                        ],
                    }
                ],
            }
        )
        normalized = _normalize_task_with_intent_fallback(
            ctx=ctx,
            intent_payload={"intent_text": "验证 heavy hitter 检测功能，让 h1 到 h2 的 TCP 流超过阈值后被丢弃。"},
            task=original,
        )
        self.assertEqual(normalized.intent_category, "stateful_policy")
        self.assertTrue(any(contract.kind == "negative" for contract in normalized.sequence_contract))


if __name__ == "__main__":
    unittest.main()
