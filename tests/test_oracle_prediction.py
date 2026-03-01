import unittest

from sagefuzz_seedgen.schemas import OraclePredictionCandidate, PacketSpec
from sagefuzz_seedgen.workflow.packet_sequence_workflow import (
    _fallback_oracle_prediction,
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

    def test_fallback_oracle_prediction(self) -> None:
        fallback = _fallback_oracle_prediction(
            task_id="T2",
            scenario="negative_probe",
            packet_sequence=self._packets(),
            reason="schema parse failed",
        )
        self.assertEqual(fallback.task_id, "T2")
        self.assertEqual(fallback.scenario, "negative_probe")
        self.assertEqual(len(fallback.packet_predictions), 2)
        self.assertTrue(all(item.expected_outcome == "unknown" for item in fallback.packet_predictions))


if __name__ == "__main__":
    unittest.main()
