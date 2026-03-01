import unittest

from agno.models.openai.like import OpenAILike
from agno.models.xai import xAI

from sagefuzz_seedgen.agents.team_factory import _build_model
from sagefuzz_seedgen.config import ModelConfig


class TestTeamFactoryModelSelection(unittest.TestCase):
    def test_build_model_uses_native_xai_for_xai_base_url(self) -> None:
        cfg = ModelConfig(
            model_id="grok-4",
            api_key="test-key",
            base_url="https://api.x.ai/v1",
            timeout_seconds=30.0,
            max_retries=2,
        )
        model = _build_model(cfg)
        self.assertIsInstance(model, xAI)

    def test_build_model_uses_openai_like_for_non_xai_base_url(self) -> None:
        cfg = ModelConfig(
            model_id="glm-4.7",
            api_key="test-key",
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            timeout_seconds=30.0,
            max_retries=2,
        )
        model = _build_model(cfg)
        self.assertIsInstance(model, OpenAILike)
        self.assertNotIsInstance(model, xAI)


if __name__ == "__main__":
    unittest.main()
