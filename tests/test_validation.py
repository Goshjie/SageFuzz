import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    FieldRelationSpec,
    PacketSpec,
    PacketStepSpec,
    SequenceScenarioSpec,
    TaskSpec,
)
from sagefuzz_seedgen.workflow.validation import validate_packet_sequence_contract


class TestValidation(unittest.TestCase):
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
            task_description="contract-driven handshake",
            feature_under_test="firewall",
            role_bindings={"initiator": "h1", "responder": "h3"},
            sequence_contract=[
                SequenceScenarioSpec(
                    scenario="positive_main",
                    kind="positive",
                    required=True,
                    allow_additional_packets=False,
                    steps=[
                        PacketStepSpec(
                            tx_role="initiator",
                            rx_role="responder",
                            protocol_stack=["Ethernet", "IPv4", "TCP"],
                            field_expectations={
                                "Ethernet.etherType": {"equals": "0x0800"},
                                "IPv4.proto": {"one_of": [6, "6"]},
                                "TCP.flags": {"contains": "S", "not_contains": "A"},
                            },
                        ),
                        PacketStepSpec(
                            tx_role="responder",
                            rx_role="initiator",
                            protocol_stack=["Ethernet", "IPv4", "TCP"],
                            field_expectations={
                                "Ethernet.etherType": {"equals": "0x0800"},
                                "IPv4.proto": {"one_of": [6, "6"]},
                                "TCP.flags": {"equals": "SA"},
                            },
                        ),
                        PacketStepSpec(
                            tx_role="initiator",
                            rx_role="responder",
                            protocol_stack=["Ethernet", "IPv4", "TCP"],
                            field_expectations={
                                "Ethernet.etherType": {"equals": "0x0800"},
                                "IPv4.proto": {"one_of": [6, "6"]},
                                "TCP.flags": {"contains": "A", "not_contains": "S"},
                            },
                        ),
                    ],
                    field_relations=[
                        FieldRelationSpec(
                            left_step=2,
                            left_field="TCP.ack",
                            op="eq",
                            right_step=1,
                            right_field="TCP.seq",
                            right_delta=1,
                        ),
                        FieldRelationSpec(
                            left_step=3,
                            left_field="TCP.ack",
                            op="eq",
                            right_step=2,
                            right_field="TCP.seq",
                            right_delta=1,
                        ),
                    ],
                )
                ,
                SequenceScenarioSpec(
                    scenario="negative_probe",
                    kind="negative",
                    required=True,
                    allow_additional_packets=False,
                    steps=[
                        PacketStepSpec(
                            tx_role="responder",
                            rx_role="initiator",
                            protocol_stack=["Ethernet", "IPv4", "TCP"],
                            field_expectations={
                                "Ethernet.etherType": {"equals": "0x0800"},
                                "IPv4.proto": {"one_of": [6, "6"]},
                                "TCP.flags": {"equals": "S"},
                            },
                        )
                    ],
                ),
            ],
        )

    def test_positive_handshake_passes(self) -> None:
        task = self._task()
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "S",
                    "TCP.seq": 1000,
                },
            ),
            PacketSpec(
                packet_id=2,
                tx_host="h3",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "SA",
                    "TCP.seq": 5000,
                    "TCP.ack": 1001,
                },
            ),
            PacketSpec(
                packet_id=3,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "A",
                    "TCP.seq": 1001,
                    "TCP.ack": 5001,
                },
            ),
            PacketSpec(
                packet_id=4,
                tx_host="h3",
                scenario="negative_probe",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "S",
                    "TCP.seq": 7000,
                },
            ),
        ]
        res = validate_packet_sequence_contract(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "PASS", res.feedback)

    def test_wrong_role_sender_fails(self) -> None:
        task = self._task()
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h3",  # wrong: first step expects initiator(h1)
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "S",
                    "TCP.seq": 1,
                },
            ),
            PacketSpec(
                packet_id=2,
                tx_host="h3",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "SA",
                    "TCP.seq": 2,
                    "TCP.ack": 2,
                },
            ),
            PacketSpec(
                packet_id=3,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "A",
                    "TCP.seq": 3,
                    "TCP.ack": 3,
                },
            ),
            PacketSpec(
                packet_id=4,
                tx_host="h3",
                scenario="negative_probe",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "S",
                    "TCP.seq": 10,
                },
            ),
        ]
        res = validate_packet_sequence_contract(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("tx_host must be", res.feedback)

    def test_relation_violation_fails(self) -> None:
        task = self._task()
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"Ethernet.etherType": "0x0800", "IPv4.proto": 6, "TCP.flags": "S", "TCP.seq": 100},
            ),
            PacketSpec(
                packet_id=2,
                tx_host="h3",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"Ethernet.etherType": "0x0800", "IPv4.proto": 6, "TCP.flags": "SA", "TCP.seq": 500, "TCP.ack": 999},
            ),
            PacketSpec(
                packet_id=3,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"Ethernet.etherType": "0x0800", "IPv4.proto": 6, "TCP.flags": "A", "TCP.seq": 101, "TCP.ack": 501},
            ),
            PacketSpec(
                packet_id=4,
                tx_host="h3",
                scenario="negative_probe",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"Ethernet.etherType": "0x0800", "IPv4.proto": 6, "TCP.flags": "S", "TCP.seq": 3000},
            ),
        ]
        res = validate_packet_sequence_contract(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "FAIL")

    def test_contains_list_expectation_supported(self) -> None:
        task = TaskSpec(
            task_id="T2",
            task_description="contains-list expectation",
            feature_under_test="generic",
            role_bindings={"initiator": "h1"},
            require_positive_and_negative=False,
            sequence_contract=[
                SequenceScenarioSpec(
                    scenario="positive_main",
                    kind="positive",
                    required=True,
                    allow_additional_packets=False,
                    steps=[
                        PacketStepSpec(
                            tx_role="initiator",
                            protocol_stack=["Ethernet", "IPv4", "TCP"],
                            field_expectations={"TCP.flags": {"contains": ["SYN", "ACK"]}},
                        )
                    ],
                )
            ],
        )
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_main",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={"TCP.flags": "SYN|ACK"},
            )
        ]
        res = validate_packet_sequence_contract(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "PASS", res.feedback)


if __name__ == "__main__":
    unittest.main()
