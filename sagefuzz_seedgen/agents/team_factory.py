from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple

from sagefuzz_seedgen.runtime.sqlite_compat import install_sqlite_compat

install_sqlite_compat()

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.like import OpenAILike
from agno.models.xai import xAI
from agno.team import Team

from sagefuzz_seedgen.agents.prompts_loader import load_prompt
from sagefuzz_seedgen.config import AgentModelOverrides, AgnoMemoryConfig, ModelConfig
from sagefuzz_seedgen.tools.control_plane_tools import (
    get_action_code_tool,
    get_table_tool,
    get_tables_tool,
)
from sagefuzz_seedgen.tools.graph_tools import (
    get_jump_dict_tool,
    get_path_constraints_tool,
    get_ranked_tables_tool,
)
from sagefuzz_seedgen.tools.parser_tools import (
    get_header_bits_tool,
    get_header_definitions_tool,
    get_parser_paths_tool,
    get_parser_transitions_tool,
)
from sagefuzz_seedgen.tools.p4_source_tools import (
    get_p4_source_info_tool,
    get_p4_source_snippet_tool,
    search_p4_source_tool,
)
from sagefuzz_seedgen.tools.state_tools import get_stateful_objects_tool
from sagefuzz_seedgen.tools.topology_tools import (
    choose_default_host_pair_tool,
    classify_host_zone_tool,
    get_host_info_tool,
    get_topology_hosts_tool,
    get_topology_links_tool,
)


def _build_model(model: ModelConfig) -> OpenAILike:
    if not model.api_key:
        raise ValueError(
            "Missing AGNO_API_KEY (or --api-key). This generator needs a model key to run the agents."
        )
    base_host = urlparse(model.base_url).netloc.lower()

    # Prefer Agno native xAI model when talking to xAI endpoints.
    if base_host.endswith("x.ai") or base_host.endswith("api.x.ai"):
        return xAI(
            id=model.model_id,
            api_key=model.api_key,
            base_url=model.base_url,
            timeout=float(model.timeout_seconds),
            max_retries=int(model.max_retries),
        )

    return OpenAILike(
        id=model.model_id,
        api_key=model.api_key,
        base_url=model.base_url,
        timeout=float(model.timeout_seconds),
        max_retries=int(model.max_retries),
    )


def _build_memory_kwargs(
    *,
    memory_cfg: AgnoMemoryConfig,
    user_id: Optional[str],
    session_id_prefix: Optional[str],
) -> Tuple[Optional[SqliteDb], Dict[str, object]]:
    if not memory_cfg.enabled:
        return None, {}

    db_path = Path(memory_cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = SqliteDb(db_file=str(db_path))

    session_prefix = session_id_prefix or "seedgen"
    base_kwargs: Dict[str, object] = {
        "db": db,
        "user_id": user_id or memory_cfg.user_id,
        "update_memory_on_run": memory_cfg.update_memory_on_run,
        "add_memories_to_context": memory_cfg.add_memories_to_context,
        "enable_session_summaries": memory_cfg.enable_session_summaries,
        "add_session_summary_to_context": memory_cfg.add_session_summary_to_context,
        "metadata": {
            "memory_backend": "agno.sqlite",
            "memory_db_path": str(db_path),
            "memory_scope": "shared_user_memory",
        },
    }
    base_kwargs["session_id_prefix"] = session_prefix
    return db, base_kwargs


def _agent_kwargs(base_kwargs: Dict[str, object], agent_key: str) -> Dict[str, object]:
    if not base_kwargs:
        return {}
    session_prefix = str(base_kwargs["session_id_prefix"])
    kwargs = dict(base_kwargs)
    kwargs.pop("session_id_prefix", None)
    kwargs["session_id"] = f"{session_prefix}:{agent_key}"
    return kwargs


_AGENT_MODEL_KEY_ALIASES = {
    "agent1": {"agent1", "semantic_analyzer", "agent1_semantic_analyzer"},
    "agent2": {"agent2", "sequence_constructor", "agent2_sequence_constructor"},
    "agent3": {"agent3", "constraint_critic", "agent3_constraint_critic"},
    "agent4": {"agent4", "entity_generator", "agent4_entity_generator"},
    "agent5": {"agent5", "entity_critic", "agent5_entity_critic"},
    "agent6": {"agent6", "oracle_predictor", "agent6_oracle_predictor"},
    "team": {"team", "seedgenteam"},
}


def _normalize_agent_model_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_agent_model_cfg(
    *,
    agent_key: str,
    default_cfg: ModelConfig,
    overrides: Optional[AgentModelOverrides],
) -> ModelConfig:
    if overrides is None:
        return default_cfg

    normalized = _normalize_agent_model_key(agent_key)
    aliases = _AGENT_MODEL_KEY_ALIASES.get(normalized, {normalized})
    for key, cfg in overrides.per_agent.items():
        if _normalize_agent_model_key(key) in aliases:
            return cfg
    if overrides.all_agents is not None:
        return overrides.all_agents
    return default_cfg


def _model_cache_key(model: ModelConfig) -> tuple[str, str, str, float, int]:
    return (
        model.model_id,
        model.api_key,
        model.base_url,
        float(model.timeout_seconds),
        int(model.max_retries),
    )


def build_agents_and_team(
    *,
    model_cfg: ModelConfig,
    prompts_dir: Path,
    agent_model_overrides: Optional[AgentModelOverrides] = None,
    memory_cfg: Optional[AgnoMemoryConfig] = None,
    memory_user_id: Optional[str] = None,
    session_id_prefix: Optional[str] = None,
) -> Tuple[Agent, Agent, Agent, Agent, Agent, Agent, Team]:
    shared = load_prompt(prompts_dir, "shared_contract.md")
    a1_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent1_semantic_analyzer.md")
    a2_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent2_sequence_constructor.md")
    a3_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent3_constraint_critic.md")
    a4_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent4_entity_generator.md")
    a5_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent5_entity_critic.md")
    a6_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent6_oracle_predictor.md")

    tools: List = [
        # CFG/graph tools
        get_jump_dict_tool,
        get_ranked_tables_tool,
        get_path_constraints_tool,
        # Parser/header tools
        get_parser_paths_tool,
        get_parser_transitions_tool,
        get_header_definitions_tool,
        get_header_bits_tool,
        # P4 source tools
        get_p4_source_info_tool,
        search_p4_source_tool,
        get_p4_source_snippet_tool,
        # Stateful tools
        get_stateful_objects_tool,
        # Topology tools
        get_topology_hosts_tool,
        get_topology_links_tool,
        get_host_info_tool,
        classify_host_zone_tool,
        choose_default_host_pair_tool,
        # Control-plane tools
        get_tables_tool,
        get_table_tool,
        get_action_code_tool,
    ]

    model_cache: Dict[tuple[str, str, str, float, int], OpenAILike] = {}

    def model_for(agent_key: str) -> OpenAILike:
        resolved_cfg = _resolve_agent_model_cfg(
            agent_key=agent_key,
            default_cfg=model_cfg,
            overrides=agent_model_overrides,
        )
        cache_key = _model_cache_key(resolved_cfg)
        cached = model_cache.get(cache_key)
        if cached is None:
            cached = _build_model(resolved_cfg)
            model_cache[cache_key] = cached
        return cached

    effective_memory_cfg = memory_cfg or AgnoMemoryConfig()
    db, memory_kwargs = _build_memory_kwargs(
        memory_cfg=effective_memory_cfg,
        user_id=memory_user_id,
        session_id_prefix=session_id_prefix,
    )

    agent1 = Agent(
        name="Semantic Analyzer",
        role="semantic_analyzer",
        model=model_for("agent1"),
        instructions=a1_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent1"),
    )

    agent2 = Agent(
        name="Sequence Constructor",
        role="sequence_constructor",
        model=model_for("agent2"),
        instructions=a2_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent2"),
    )

    agent3 = Agent(
        name="Constraint Critic",
        role="constraint_critic",
        model=model_for("agent3"),
        instructions=a3_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent3"),
    )

    agent4 = Agent(
        name="Entity Generator",
        role="entity_generator",
        model=model_for("agent4"),
        instructions=a4_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent4"),
    )

    agent5 = Agent(
        name="Entity Critic",
        role="entity_critic",
        model=model_for("agent5"),
        instructions=a5_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent5"),
    )

    agent6 = Agent(
        name="Oracle Predictor",
        role="oracle_predictor",
        model=model_for("agent6"),
        instructions=a6_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
        **_agent_kwargs(memory_kwargs, "agent6"),
    )

    team = Team(
        members=[agent1, agent2, agent3, agent4, agent5, agent6],
        name="SeedgenTeam",
        model=model_for("team"),
        share_member_interactions=True,
        add_team_history_to_members=True,
        num_team_history_runs=3,
        markdown=False,
        **(
            {
                "db": db,
                "user_id": memory_user_id or effective_memory_cfg.user_id,
                "session_id": f"{session_id_prefix or 'seedgen'}:team",
                "update_memory_on_run": effective_memory_cfg.update_memory_on_run,
                "add_memories_to_context": effective_memory_cfg.add_memories_to_context,
                "enable_session_summaries": effective_memory_cfg.enable_session_summaries,
                "add_session_summary_to_context": effective_memory_cfg.add_session_summary_to_context,
            }
            if db is not None
            else {}
        ),
    )

    return agent1, agent2, agent3, agent4, agent5, agent6, team
