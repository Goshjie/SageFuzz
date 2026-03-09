import unittest

from sagefuzz_seedgen.cli import _build_agent_model_overrides
from sagefuzz_seedgen.config import ModelConfig


class TestCliAgentModelOverrides(unittest.TestCase):
    def setUp(self) -> None:
        self.base_model = ModelConfig(
            model_id="glm-4.7",
            api_key="base-key",
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            timeout_seconds=30.0,
            max_retries=2,
        )

    def test_build_agent_model_overrides_empty(self) -> None:
        overrides = _build_agent_model_overrides({}, base_model=self.base_model)
        self.assertIsNone(overrides.all_agents)
        self.assertEqual(overrides.per_agent, {})

    def test_build_agent_model_overrides_agent5_only(self) -> None:
        overrides = _build_agent_model_overrides(
            {
                "agent_models": {
                    "agent5": {
                        "model_id": "qwen2.5-7b-instruct",
                        "api_key": "small-key",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    }
                }
            },
            base_model=self.base_model,
        )
        self.assertIsNone(overrides.all_agents)
        self.assertIn("agent5", overrides.per_agent)
        self.assertEqual(overrides.per_agent["agent5"].model_id, "qwen2.5-7b-instruct")
        self.assertEqual(overrides.per_agent["agent5"].timeout_seconds, 30.0)
        self.assertEqual(overrides.per_agent["agent5"].max_retries, 2)

    def test_build_agent_model_overrides_all_agents_with_specific_override(self) -> None:
        overrides = _build_agent_model_overrides(
            {
                "agent_models": {
                    "all_agents": {
                        "model_id": "qwen2.5-7b-instruct",
                        "api_key": "small-key",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "timeout_seconds": 45,
                        "max_retries": 1,
                    },
                    "agent5": {
                        "model_id": "qwen3.5-4b",
                    },
                }
            },
            base_model=self.base_model,
        )
        self.assertIsNotNone(overrides.all_agents)
        assert overrides.all_agents is not None
        self.assertEqual(overrides.all_agents.model_id, "qwen2.5-7b-instruct")
        self.assertEqual(overrides.per_agent["agent5"].model_id, "qwen3.5-4b")
        self.assertEqual(
            overrides.per_agent["agent5"].base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(overrides.per_agent["agent5"].timeout_seconds, 45.0)
        self.assertEqual(overrides.per_agent["agent5"].max_retries, 1)


if __name__ == "__main__":
    unittest.main()
