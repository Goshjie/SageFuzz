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
                        "sequence_order": 1,
                        "expected_outcome": "deliver",
                        "expected_rx_host": "h2",
                        "processing_decision": "forward via table entry #1",
                        "expected_switch_state_before": "conn[h1->h2]=new",
                        "expected_switch_state_after": "conn[h1->h2]=tracked",
                        "rationale": "contract allows this direction",
                    },
                    {
                        "packet_id": 2,
                        "sequence_order": 2,
                        "expected_outcome": "drop",
                        "processing_decision": "drop by policy",
                        "expected_switch_state_before": "conn[h1->h2]=tracked",
                        "expected_switch_state_after": "conn[h1->h2]=tracked",
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
                    {
                        "packet_id": 1,
                        "sequence_order": 1,
                        "expected_outcome": "unknown",
                        "processing_decision": "unknown",
                        "expected_switch_state_before": "unknown",
                        "expected_switch_state_after": "unknown",
                        "rationale": "insufficient evidence",
                    }
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
        self.assertEqual([item.sequence_order for item in fallback.packet_predictions], [1, 2])

    def test_deliver_without_expected_rx_host_fails(self) -> None:
        prediction = OraclePredictionCandidate.model_validate(
            {
                "task_id": "T1",
                "scenario": "positive_main",
                "packet_predictions": [
                    {
                        "packet_id": 1,
                        "sequence_order": 1,
                        "expected_outcome": "deliver",
                        "processing_decision": "forward",
                        "expected_switch_state_before": "state=init",
                        "expected_switch_state_after": "state=tracked",
                        "rationale": "should deliver",
                    },
                    {
                        "packet_id": 2,
                        "sequence_order": 2,
                        "expected_outcome": "drop",
                        "processing_decision": "drop",
                        "expected_switch_state_before": "state=tracked",
                        "expected_switch_state_after": "state=tracked",
                        "rationale": "blocked",
                    },
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
        self.assertIn("requires expected_rx_host", feedback)

    def test_sequence_order_mismatch_fails(self) -> None:
        prediction = OraclePredictionCandidate.model_validate(
            {
                "task_id": "T1",
                "scenario": "positive_main",
                "packet_predictions": [
                    {
                        "packet_id": 1,
                        "sequence_order": 2,
                        "expected_outcome": "deliver",
                        "expected_rx_host": "h2",
                        "processing_decision": "forward",
                        "expected_switch_state_before": "state=init",
                        "expected_switch_state_after": "state=tracked",
                        "rationale": "ok",
                    },
                    {
                        "packet_id": 2,
                        "sequence_order": 1,
                        "expected_outcome": "drop",
                        "processing_decision": "drop",
                        "expected_switch_state_before": "state=tracked",
                        "expected_switch_state_after": "state=tracked",
                        "rationale": "ok",
                    },
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
        self.assertIn("sequence_order does not match", feedback)


if __name__ == "__main__":
    unittest.main()
