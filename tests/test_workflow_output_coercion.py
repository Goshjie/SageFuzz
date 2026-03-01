import unittest

from sagefuzz_seedgen.schemas import Agent1Output
from sagefuzz_seedgen.workflow.packet_sequence_workflow import _coerce_schema_output


class TestWorkflowOutputCoercion(unittest.TestCase):
    def test_coerce_dict_to_schema(self) -> None:
        raw = {"kind": "questions", "questions": []}
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")

    def test_coerce_json_string_to_schema(self) -> None:
        raw = '{"kind":"questions","questions":[]}'
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")

    def test_invalid_string_returns_none(self) -> None:
        out = _coerce_schema_output("not json", Agent1Output)
        self.assertIsNone(out)

    def test_mixed_string_extracts_json_object(self) -> None:
        raw = 'prefix text {"kind":"questions","questions":[]} trailing'
        out = _coerce_schema_output(raw, Agent1Output)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.kind, "questions")


if __name__ == "__main__":
    unittest.main()
