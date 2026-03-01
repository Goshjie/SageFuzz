import json
import tempfile
import unittest
from pathlib import Path

from sagefuzz_seedgen.schemas import OraclePredictionCandidate, PacketSpec, RuntimePacketObservation
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _compare_oracle_prediction_to_runtime,
    _load_runtime_observations,
    _validate_oracle_prediction_candidate,
)


class TestOraclePredictionHelpers(unittest.TestCase):
    def _packets(self) -> list[PacketSpec]:
        return [
            PacketSpec(packet_id=1, tx_host="h1", scenario="positive_main", protocol_stack=["Ethernet"], fields={}),
            PacketSpec(packet_id=2, tx_host="h2", scenario="positive_main", protocol_stack=["Ethernet"], fields={}),
        ]

    def _prediction(self) -> OraclePredictionCandidate:
        return OraclePredictionCandidate.model_validate(
            {
                "task_id": "T1",
                "scenario": "positive_main",
                "packet_predictions": [
                    {
                        "packet_id": 1,
                        "expected_outcome": "deliver",
                        "expected_rx_host": "h2",
                        "rationale": "contract allows this direction",
                    },
                    {
                        "packet_id": 2,
                        "expected_outcome": "drop",
                        "rationale": "negative scenario packet",
                    },
                ],
            }
        )

    def test_validate_oracle_prediction_candidate_pass(self) -> None:
        feedback = _validate_oracle_prediction_candidate(
            task_id="T1",
            scenario="positive_main",
            packet_sequence=self._packets(),
            prediction=self._prediction(),
        )
        self.assertIsNone(feedback)

    def test_validate_oracle_prediction_candidate_detects_missing_packet(self) -> None:
        prediction = OraclePredictionCandidate.model_validate(
            {
                "task_id": "T1",
                "scenario": "positive_main",
                "packet_predictions": [
                    {"packet_id": 1, "expected_outcome": "unknown", "rationale": "insufficient evidence"}
                ],
            }
        )
        feedback = _validate_oracle_prediction_candidate(
            task_id="T1",
            scenario="positive_main",
            packet_sequence=self._packets(),
            prediction=prediction,
        )
        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertIn("missing packet_id", feedback)

    def test_compare_oracle_prediction_pending_runtime(self) -> None:
        out = _compare_oracle_prediction_to_runtime(
            prediction=self._prediction(),
            runtime_packets=None,
        )
        self.assertEqual(out["status"], "PENDING_RUNTIME")
        self.assertEqual(out["total_packets"], 2)

    def test_compare_oracle_prediction_match(self) -> None:
        runtime = [
            RuntimePacketObservation(packet_id=1, observed_outcome="deliver", observed_rx_host="h2"),
            RuntimePacketObservation(packet_id=2, observed_outcome="drop"),
        ]
        out = _compare_oracle_prediction_to_runtime(
            prediction=self._prediction(),
            runtime_packets=runtime,
        )
        self.assertEqual(out["status"], "MATCH")
        self.assertEqual(len(out["mismatches"]), 0)

    def test_compare_oracle_prediction_mismatch(self) -> None:
        runtime = [
            RuntimePacketObservation(packet_id=1, observed_outcome="drop"),
            RuntimePacketObservation(packet_id=2, observed_outcome="drop"),
        ]
        out = _compare_oracle_prediction_to_runtime(
            prediction=self._prediction(),
            runtime_packets=runtime,
        )
        self.assertEqual(out["status"], "MISMATCH")
        self.assertGreaterEqual(len(out["mismatches"]), 1)

    def test_load_runtime_observations(self) -> None:
        payload = {
            "scenarios": {
                "positive_main": {
                    "packets": [
                        {"packet_id": 1, "observed_outcome": "deliver", "observed_rx_host": "h2"},
                        {"packet_id": 2, "observed_outcome": "drop"},
                    ]
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "runtime_obs.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            out = _load_runtime_observations(p)
        self.assertIn("positive_main", out)
        self.assertEqual(len(out["positive_main"]), 2)


if __name__ == "__main__":
    unittest.main()
