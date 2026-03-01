from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from typing import List, Tuple

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.models.xai import xAI
from agno.team import Team

from sagefuzz_seedgen.agents.prompts_loader import load_prompt
from sagefuzz_seedgen.config import ModelConfig
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


def build_agents_and_team(*, model_cfg: ModelConfig, prompts_dir: Path) -> Tuple[Agent, Agent, Agent, Agent, Agent, Team]:
    shared = load_prompt(prompts_dir, "shared_contract.md")
    a1_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent1_semantic_analyzer.md")
    a2_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent2_sequence_constructor.md")
    a3_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent3_constraint_critic.md")
    a4_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent4_entity_generator.md")
    a5_prompt = shared + "\n\n" + load_prompt(prompts_dir, "agent5_entity_critic.md")

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

    model = _build_model(model_cfg)

    agent1 = Agent(
        name="Semantic Analyzer",
        role="semantic_analyzer",
        model=model,
        instructions=a1_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
    )

    agent2 = Agent(
        name="Sequence Constructor",
        role="sequence_constructor",
        model=model,
        instructions=a2_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
    )

    agent3 = Agent(
        name="Constraint Critic",
        role="constraint_critic",
        model=model,
        instructions=a3_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
    )

    agent4 = Agent(
        name="Entity Generator",
        role="entity_generator",
        model=model,
        instructions=a4_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
    )

    agent5 = Agent(
        name="Entity Critic",
        role="entity_critic",
        model=model,
        instructions=a5_prompt,
        tools=tools,
        markdown=False,
        use_json_mode=True,
    )

    team = Team(
        members=[agent1, agent2, agent3, agent4, agent5],
        name="SeedgenTeam",
        model=model,
        share_member_interactions=True,
        add_team_history_to_members=True,
        num_team_history_runs=3,
        markdown=False,
    )

    return agent1, agent2, agent3, agent4, agent5, team
