import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.tools.p4_source_tools import (
    get_p4_source_info,
    get_p4_source_snippet,
    search_p4_source,
)


class TestP4SourceToolsWithSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
            p4_source_path=Path("P4/firewall/solution/firewall.p4"),
        )
        set_program_context(ctx)

    def test_get_p4_source_info(self) -> None:
        info = get_p4_source_info()
        self.assertTrue(info.get("available"))
        self.assertTrue((info.get("line_count") or 0) > 100)
        self.assertTrue(str(info.get("path") or "").endswith("P4/firewall/solution/firewall.p4"))

    def test_search_p4_source(self) -> None:
        result = search_p4_source(query="table check_ports")
        self.assertTrue(result.get("available"))
        self.assertGreaterEqual(int(result.get("total_matches") or 0), 1)
        matches = result.get("matches") or []
        self.assertTrue(any("check_ports" in str(item.get("line", "")) for item in matches))

    def test_get_p4_source_snippet(self) -> None:
        snippet = get_p4_source_snippet(start_line=168, end_line=180)
        self.assertTrue(snippet.get("available"))
        lines = snippet.get("lines") or []
        self.assertTrue(any("set_direction" in str(item.get("line", "")) for item in lines))


class TestP4SourceToolsWithoutSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
        )
        set_program_context(ctx)

    def test_info_reports_unavailable(self) -> None:
        info = get_p4_source_info()
        self.assertFalse(info.get("available"))
        self.assertEqual(info.get("line_count"), 0)


if __name__ == "__main__":
    unittest.main()

