import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.tools.control_plane_tools import get_action_code, get_table, get_tables


class TestControlPlaneTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/firewall/build/firewall.json"),
            graphs_dir=Path("P4/firewall/build/graphs"),
            p4info_path=Path("P4/firewall/build/firewall.p4.p4info.txtpb"),
            topology_path=Path("P4/firewall/pod-topo/topology.json"),
        )
        set_program_context(ctx)

    def test_get_tables_contains_ipv4_lpm(self) -> None:
        tables = get_tables()
        names = {table.get("name") for table in tables}
        self.assertIn("MyIngress.ipv4_lpm", names)

    def test_get_table_returns_key_and_actions(self) -> None:
        table = get_table("MyIngress.ipv4_lpm")
        self.assertTrue(table.get("found"))
        keys = table.get("keys") or []
        self.assertTrue(any(key.get("field") == "hdr.ipv4.dstAddr" for key in keys))
        actions = table.get("actions") or []
        self.assertIn("MyIngress.ipv4_forward", actions)

    def test_get_action_code_runtime_data(self) -> None:
        action = get_action_code("MyIngress.ipv4_forward")
        self.assertTrue(action.get("found"))
        runtime_data = action.get("runtime_data") or []
        param_names = {param.get("name") for param in runtime_data}
        self.assertEqual(param_names, {"dstAddr", "port"})


if __name__ == "__main__":
    unittest.main()
