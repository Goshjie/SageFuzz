import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import PacketSpec, TableRule, TaskSpec
from sagefuzz_seedgen.workflow.validation import validate_control_plane_entities


class TestEntityValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
        )

    def _task(self) -> TaskSpec:
        return TaskSpec(
            task_id="T",
            task_description="",
            feature_under_test="firewall",
            internal_host="h1",
            external_host="h3",
            require_positive_handshake=True,
            include_negative_external_initiation=True,
        )

    def _packets(self) -> list[PacketSpec]:
        return [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_handshake",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"IPv4.src": "10.0.1.1", "IPv4.dst": "10.0.3.3", "TCP.flags": "S"},
            ),
            PacketSpec(
                packet_id=2,
                tx_host="h3",
                scenario="positive_handshake",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"IPv4.src": "10.0.3.3", "IPv4.dst": "10.0.1.1", "TCP.flags": "SA"},
            ),
        ]

    def test_valid_entities_pass(self) -> None:
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.3.3", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:03:33", "port": 3},
            ),
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.1.1", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:01:11", "port": 1},
            ),
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=self._packets(),
            entities=entities,
        )
        self.assertEqual(res.status, "PASS", res.feedback)

    def test_missing_action_param_fails(self) -> None:
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.3.3", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"port": 3},
            )
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=self._packets(),
            entities=entities,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("missing action_data parameter", res.feedback)

    def test_missing_destination_coverage_fails(self) -> None:
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.3.3", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:03:33", "port": 3},
            )
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=self._packets(),
            entities=entities,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("destination IP", res.feedback)


if __name__ == "__main__":
    unittest.main()
