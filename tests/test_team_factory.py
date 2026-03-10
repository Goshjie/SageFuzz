import tempfile
import unittest
from pathlib import Path

from agno.models.dashscope import DashScope
from agno.models.openai.like import OpenAILike
from agno.models.xai import xAI

from sagefuzz_seedgen.agents.team_factory import _build_model, build_agents_and_team
from sagefuzz_seedgen.config import AgentModelOverrides, AgnoMemoryConfig, ModelConfig


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

    def test_build_model_uses_native_dashscope_for_dashscope_base_url(self) -> None:
        cfg = ModelConfig(
            model_id="qwen2.5-7b-instruct",
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout_seconds=30.0,
            max_retries=2,
        )
        model = _build_model(cfg)
        self.assertIsInstance(model, DashScope)


class TestTeamFactoryMemoryIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.model_cfg = ModelConfig(
            model_id="glm-4.7",
            api_key="test-key",
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            timeout_seconds=30.0,
            max_retries=2,
        )
        self.prompts_dir = Path("prompts")

    def test_build_agents_and_team_enables_agno_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_cfg = AgnoMemoryConfig(
                enabled=True,
                db_path=Path(tmpdir) / "agno_memory.db",
                user_id="memory-user",
                update_memory_on_run=True,
                add_memories_to_context=True,
            )
            agent1, agent2, _agent3, _agent4, _agent5, _agent6, team = build_agents_and_team(
                model_cfg=self.model_cfg,
                prompts_dir=self.prompts_dir,
                memory_cfg=memory_cfg,
                memory_user_id="memory-user",
                session_id_prefix="run-123",
            )

            self.assertIsNotNone(agent1.db)
            self.assertIs(agent1.db, agent2.db)
            self.assertEqual(agent1.user_id, "memory-user")
            self.assertEqual(agent1.session_id, "run-123:agent1")
            self.assertEqual(agent2.session_id, "run-123:agent2")
            self.assertTrue(agent1.update_memory_on_run)
            self.assertTrue(agent1.add_memories_to_context)
            self.assertEqual(team.user_id, "memory-user")
            self.assertEqual(team.session_id, "run-123:team")

    def test_build_agents_and_team_can_disable_agno_memory(self) -> None:
        memory_cfg = AgnoMemoryConfig(enabled=False)

        agent1, _agent2, _agent3, _agent4, _agent5, _agent6, team = build_agents_and_team(
            model_cfg=self.model_cfg,
            prompts_dir=self.prompts_dir,
            memory_cfg=memory_cfg,
            memory_user_id="memory-user",
            session_id_prefix="run-123",
        )

        self.assertIsNone(agent1.db)
        self.assertFalse(agent1.update_memory_on_run)
        self.assertIsNone(team.db)

    def test_build_agents_and_team_supports_agent5_override(self) -> None:
        override_cfg = ModelConfig(
            model_id="qwen2.5-7b-instruct",
            api_key="small-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout_seconds=45.0,
            max_retries=1,
        )
        overrides = AgentModelOverrides(per_agent={"agent5": override_cfg})

        agent1, _agent2, _agent3, _agent4, agent5, _agent6, team = build_agents_and_team(
            model_cfg=self.model_cfg,
            prompts_dir=self.prompts_dir,
            agent_model_overrides=overrides,
        )

        self.assertEqual(agent1.model.id, "glm-4.7")
        self.assertEqual(agent5.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(team.model.id, "glm-4.7")

    def test_build_agents_and_team_supports_all_agent_override(self) -> None:
        override_cfg = ModelConfig(
            model_id="qwen2.5-7b-instruct",
            api_key="small-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout_seconds=45.0,
            max_retries=1,
        )
        overrides = AgentModelOverrides(all_agents=override_cfg)

        agent1, agent2, agent3, agent4, agent5, agent6, team = build_agents_and_team(
            model_cfg=self.model_cfg,
            prompts_dir=self.prompts_dir,
            agent_model_overrides=overrides,
        )

        self.assertEqual(agent1.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(agent2.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(agent3.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(agent4.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(agent5.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(agent6.model.id, "qwen2.5-7b-instruct")
        self.assertEqual(team.model.id, "qwen2.5-7b-instruct")


if __name__ == "__main__":
    unittest.main()
