import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.tools.parser_tools import get_header_bits, get_parser_paths, get_parser_transitions
from sagefuzz_seedgen.tools.topology_tools import classify_host_zone, get_host_info


class TestParserAndTopologyTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
        )
        set_program_context(ctx)
        cls.ctx = ctx

    def test_parser_paths_include_ipv4_tcp(self) -> None:
        paths = get_parser_paths()
        self.assertTrue(any(p[:3] == ["Ethernet", "IPv4", "TCP"] for p in paths))

    def test_parser_transitions_include_etherType_ipv4(self) -> None:
        trs = get_parser_transitions()
        self.assertTrue(
            any(t.get("field") == "Ethernet.etherType" and str(t.get("value")).lower() == "0x0800" for t in trs)
        )

    def test_header_bits(self) -> None:
        self.assertEqual(get_header_bits("Ethernet.etherType"), 16)
        # IPv4.proto is an alias to ipv4.protocol in BMv2 json.
        self.assertEqual(get_header_bits("IPv4.proto"), 8)

    def test_topology_zone_classification(self) -> None:
        z1 = classify_host_zone("h1")
        z3 = classify_host_zone("h3")
        self.assertEqual(z1["zone"], "internal")
        self.assertEqual(z3["zone"], "external")

    def test_host_tools_with_host_id(self) -> None:
        z3 = classify_host_zone(host_id="h3")
        h1 = get_host_info(host_id="h1")
        self.assertEqual(z3["zone"], "external")
        self.assertEqual(h1["host_id"], "h1")
        self.assertTrue(isinstance(h1.get("ip"), str))


if __name__ == "__main__":
    unittest.main()
