import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import ControlPlaneOperation, ExecutionOperation, PacketSpec, TaskSpec, TableRule
from sagefuzz_seedgen.workflow.validation import validate_control_plane_entities, validate_execution_sequence


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
            role_bindings={"initiator": "h1", "responder": "h3"},
            sequence_contract=[],
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
        control_plane_sequence = [
            ControlPlaneOperation(
                order=1,
                operation_type="apply_table_entry",
                target="MyIngress.ipv4_lpm",
                entity_index=1,
                parameters={"action_name": "MyIngress.ipv4_forward"},
            ),
            ControlPlaneOperation(
                order=2,
                operation_type="apply_table_entry",
                target="MyIngress.ipv4_lpm",
                entity_index=2,
                parameters={"action_name": "MyIngress.ipv4_forward"},
            ),
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=self._packets(),
            entities=entities,
            control_plane_sequence=control_plane_sequence,
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

    def test_mismatched_match_type_fails(self) -> None:
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="exact",
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
        self.assertIn("match_type", res.feedback)

    def test_ternary_table_requires_priority(self) -> None:
        # Inject a synthetic ternary table to verify priority checks.
        self.ctx.tables_by_name["Synthetic.ternary"] = {
            "actions": ["MyIngress.ipv4_forward"],
            "key": [{"target": ["ipv4", "dstAddr"], "match_type": "ternary"}],
        }
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_handshake",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"IPv4.src": "10.0.1.1", "IPv4.dst": "10.0.3.3", "TCP.flags": "S"},
            ),
        ]
        entities = [
            TableRule(
                table_name="Synthetic.ternary",
                match_type="ternary",
                match_keys={"hdr.ipv4.dstAddr": {"value": "10.0.3.3", "mask": "255.255.255.255"}},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:03:33", "port": 3},
            )
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=packets,
            entities=entities,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("requires priority", res.feedback)

        entities[0].priority = 10
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=packets,
            entities=entities,
        )
        self.assertEqual(res.status, "PASS", res.feedback)

    def test_control_plane_sequence_requires_apply_order(self) -> None:
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
        bad_sequence = [
            ControlPlaneOperation(
                order=1,
                operation_type="apply_table_entry",
                target="MyIngress.ipv4_lpm",
                entity_index=2,
                parameters={},
            ),
            ControlPlaneOperation(
                order=2,
                operation_type="apply_table_entry",
                target="MyIngress.ipv4_lpm",
                entity_index=1,
                parameters={},
            ),
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=self._packets(),
            entities=entities,
            control_plane_sequence=bad_sequence,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("entity_index order", res.feedback)

    def test_control_plane_sequence_requires_strict_order(self) -> None:
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.3.3", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:03:33", "port": 3},
            )
        ]
        bad_sequence = [
            ControlPlaneOperation(
                order=1,
                operation_type="apply_table_entry",
                target="MyIngress.ipv4_lpm",
                entity_index=1,
                parameters={},
            ),
            ControlPlaneOperation(
                order=1,
                operation_type="read_register",
                target="reg_state",
                parameters={"index": 0},
            ),
        ]
        res = validate_control_plane_entities(
            ctx=self.ctx,
            task=self._task(),
            packet_sequence=[self._packets()[0]],
            entities=entities,
            control_plane_sequence=bad_sequence,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("strictly increasing", res.feedback)

    def test_execution_sequence_pass(self) -> None:
        packets = self._packets()
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
        control_plane_sequence = [
            ControlPlaneOperation(order=1, operation_type="apply_table_entry", target="MyIngress.ipv4_lpm", entity_index=1),
            ControlPlaneOperation(order=2, operation_type="apply_table_entry", target="MyIngress.ipv4_lpm", entity_index=2),
            ControlPlaneOperation(order=3, operation_type="read_register", target="conn_state", parameters={"index": 0}),
        ]
        execution_sequence = [
            ExecutionOperation(order=1, operation_type="apply_table_entry", entity_index=1, control_plane_order=1),
            ExecutionOperation(order=2, operation_type="apply_table_entry", entity_index=2, control_plane_order=2),
            ExecutionOperation(order=3, operation_type="send_packet", packet_id=1),
            ExecutionOperation(order=4, operation_type="read_register", target="conn_state", control_plane_order=3),
            ExecutionOperation(order=5, operation_type="send_packet", packet_id=2),
        ]
        res = validate_execution_sequence(
            packet_sequence=packets,
            entities=entities,
            control_plane_sequence=control_plane_sequence,
            execution_sequence=execution_sequence,
        )
        self.assertEqual(res.status, "PASS", res.feedback)

    def test_execution_sequence_detects_missing_packet_send(self) -> None:
        packets = self._packets()
        entities = [
            TableRule(
                table_name="MyIngress.ipv4_lpm",
                match_type="lpm",
                match_keys={"hdr.ipv4.dstAddr": ["10.0.3.3", 32]},
                action_name="MyIngress.ipv4_forward",
                action_data={"dstAddr": "08:00:00:00:03:33", "port": 3},
            )
        ]
        control_plane_sequence = [
            ControlPlaneOperation(order=1, operation_type="apply_table_entry", target="MyIngress.ipv4_lpm", entity_index=1),
        ]
        execution_sequence = [
            ExecutionOperation(order=1, operation_type="apply_table_entry", entity_index=1, control_plane_order=1),
            ExecutionOperation(order=2, operation_type="send_packet", packet_id=1),
        ]
        res = validate_execution_sequence(
            packet_sequence=packets,
            entities=entities,
            control_plane_sequence=control_plane_sequence,
            execution_sequence=execution_sequence,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("send_packet order/coverage mismatch", res.feedback)


if __name__ == "__main__":
    unittest.main()
