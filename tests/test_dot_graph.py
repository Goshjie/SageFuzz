import unittest
from pathlib import Path

from sagefuzz_seedgen.dot.dot_loader import load_dot_graphs


class TestDotGraph(unittest.TestCase):
    def test_load_and_rank_tables(self) -> None:
        graphs = load_dot_graphs(Path("P4/firewall/build/graphs"))
        self.assertIn("MyIngress", graphs)
        g = graphs["MyIngress"]

        ranked = g.ranked_tables()
        tables = [t for t, _d in ranked]
        self.assertIn("MyIngress.ipv4_lpm", tables)

    def test_path_constraints_contains_isvalid(self) -> None:
        graphs = load_dot_graphs(Path("P4/firewall/build/graphs"))
        g = graphs["MyIngress"]
        constraints = g.path_constraints(target_label="MyIngress.ipv4_lpm")
        # We expect to see hdr.ipv4.isValid() in the path to ipv4_lpm for this program.
        self.assertTrue(any("isValid" in ent.get("node", "") for ent in constraints))


if __name__ == "__main__":
    unittest.main()

