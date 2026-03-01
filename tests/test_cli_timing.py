import json
import tempfile
import unittest
from pathlib import Path

from sagefuzz_seedgen.cli import _load_intent_to_testcase_seconds


class TestCliTiming(unittest.TestCase):
    def test_load_intent_to_testcase_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "index.json"
            p.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "timing": {
                            "intent_to_testcase_seconds": 1.2345,
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertAlmostEqual(_load_intent_to_testcase_seconds(p), 1.2345, places=4)

    def test_missing_timing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "index.json"
            p.write_text(json.dumps({"schema_version": "2.0"}), encoding="utf-8")
            self.assertIsNone(_load_intent_to_testcase_seconds(p))

if __name__ == "__main__":
    unittest.main()
