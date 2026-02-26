import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import PacketSpec, TaskSpec
from sagefuzz_seedgen.workflow.validation import validate_directional_tcp_state_trigger


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
        )

    def test_positive_handshake_passes(self) -> None:
        task = TaskSpec(
            task_id="T",
            task_description="",
            internal_host="h1",
            external_host="h3",
            require_positive_handshake=True,
            include_negative_external_initiation=False,
        )
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h1",
                scenario="positive_handshake",
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
                scenario="positive_handshake",
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
                scenario="positive_handshake",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "A",
                    "TCP.seq": 1001,
                    "TCP.ack": 5001,
                },
            ),
        ]
        res = validate_directional_tcp_state_trigger(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "PASS", res.feedback)

    def test_external_initiation_fails_direction(self) -> None:
        task = TaskSpec(
            task_id="T",
            task_description="",
            internal_host="h1",
            external_host="h3",
            require_positive_handshake=True,
            include_negative_external_initiation=False,
        )
        packets = [
            PacketSpec(
                packet_id=1,
                tx_host="h3",  # wrong: external initiates
                scenario="positive_handshake",
                protocol_stack=["Ethernet", "IPv4", "TCP"],
                fields={
                    "Ethernet.etherType": "0x0800",
                    "IPv4.proto": 6,
                    "TCP.flags": "S",
                    "TCP.seq": 1,
                },
            )
        ]
        res = validate_directional_tcp_state_trigger(ctx=self.ctx, task=task, packet_sequence=packets)
        self.assertEqual(res.status, "FAIL")


if __name__ == "__main__":
    unittest.main()

