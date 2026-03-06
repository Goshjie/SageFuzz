import unittest
from pathlib import Path

from sagefuzz_seedgen.runtime.initializer import initialize_program_context


class TestTopologyNormalization(unittest.TestCase):
    def test_initialize_program_context_accepts_p4app_topology(self) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/Heavy_Hitter_Detector/build/heavy_hitter.json"),
            graphs_dir=Path("P4/Heavy_Hitter_Detector/build/graphs"),
            p4info_path=Path("P4/Heavy_Hitter_Detector/build/heavy_hitter.p4.p4info.txt"),
            topology_path=Path("P4/Heavy_Hitter_Detector/p4app.json"),
            p4_source_path=Path("P4/Heavy_Hitter_Detector/solution/heavy_hitter.p4"),
        )
        self.assertIn("h1", ctx.host_info)
        self.assertIn("h2", ctx.host_info)
        self.assertTrue(str(ctx.host_info["h1"].get("ip", "")).startswith("10."))
        self.assertEqual(ctx.host_to_switch.get("h1"), "s1")

    def test_initialize_program_context_accepts_node_link_topology(self) -> None:
        ctx = initialize_program_context(
            bmv2_json_path=Path("P4/Congestion_Aware_Load_Balancing/build/loadbalancer.json"),
            graphs_dir=Path("P4/Congestion_Aware_Load_Balancing/build/graphs"),
            p4info_path=Path("P4/Congestion_Aware_Load_Balancing/build/loadbalancer.p4.p4info.txt"),
            topology_path=Path("P4/Congestion_Aware_Load_Balancing/topology.json"),
            p4_source_path=Path("P4/Congestion_Aware_Load_Balancing/p4src/loadbalancer.p4"),
        )
        self.assertIn("h1", ctx.host_info)
        self.assertIn("h8", ctx.host_info)
        self.assertTrue(str(ctx.host_info["h1"].get("ip", "")).startswith("10."))
        self.assertEqual(ctx.host_to_switch.get("h1"), "s1")


if __name__ == "__main__":
    unittest.main()
