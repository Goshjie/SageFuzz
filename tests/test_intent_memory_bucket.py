import unittest
from pathlib import Path

from sagefuzz_seedgen.config import AgnoMemoryConfig, ProgramPaths, RunConfig
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _derive_intent_memory_bucket,
    _resolve_memory_user_id,
)


class TestIntentMemoryBucket(unittest.TestCase):
    def _dummy_cfg(self) -> RunConfig:
        return RunConfig(
            program=ProgramPaths(
                bmv2_json=Path("."),
                graphs_dir=Path("."),
                p4info_txtpb=Path("."),
                topology_json=Path("."),
                p4_source=None,
            ),
            model=None,
            memory=AgnoMemoryConfig(user_id="sagefuzz-local-user"),
        )

    def test_similar_directional_firewall_intents_share_bucket(self) -> None:
        intent_a = {
            "feature_under_test": "fw_alpha",
            "intent_text": (
                "拓扑里 h1 和 h2 是内部主机，其他是外部主机。"
                "测试有状态防火墙是否只允许内部主动向外部发起 TCP 通信，"
                "外部只能回包，反向主动发起应被阻止。"
            ),
            "test_objective": "data_plane_behavior",
        }
        intent_b = {
            "feature_under_test": "different_program_name",
            "intent_text": (
                "In another P4 program, hosts h7/h8 are inside and h9 is outside. "
                "Verify that stateful policy allows internal initiation and reply traffic, "
                "but blocks external initiation."
            ),
            "test_objective": "1",
        }

        self.assertEqual(_derive_intent_memory_bucket(intent_a), _derive_intent_memory_bucket(intent_b))

    def test_control_plane_and_data_plane_use_different_buckets(self) -> None:
        base_intent = {
            "intent_text": "测试内部向外部主动发起连接是否允许，外部主动发起是否禁止。",
        }
        data_plane_bucket = _derive_intent_memory_bucket(
            {**base_intent, "test_objective": "data_plane_behavior"}
        )
        control_plane_bucket = _derive_intent_memory_bucket(
            {**base_intent, "test_objective": "control_plane_rules"}
        )

        self.assertNotEqual(data_plane_bucket, control_plane_bucket)

    def test_resolve_memory_user_id_appends_intent_bucket(self) -> None:
        cfg = self._dummy_cfg()
        user_id = _resolve_memory_user_id(
            cfg=cfg,
            intent_payload={
                "intent_text": "链路监控场景下发送探测包并观察链路利用率变化。",
                "test_objective": "data_plane_behavior",
            },
        )

        self.assertTrue(user_id.startswith("sagefuzz-local-user:intent-"))
        self.assertIn("measurement_observation", user_id)


if __name__ == "__main__":
    unittest.main()


class TestIntentMemoryBucketGeneralization(unittest.TestCase):
    def test_forwarding_intent_uses_forwarding_bucket_not_policy(self) -> None:
        bucket = _derive_intent_memory_bucket(
            {
                "intent_text": "验证 IPv4 路由转发是否把报文送到正确下一跳。",
                "test_objective": "data_plane_behavior",
            }
        )
        self.assertIn("forwarding_behavior", bucket)
        self.assertNotIn("communication_policy", bucket)

