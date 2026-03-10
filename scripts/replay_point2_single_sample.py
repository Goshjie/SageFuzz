from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagefuzz_seedgen.agents.team_factory import build_agents_and_team
from sagefuzz_seedgen.config import ModelConfig
from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    Agent1Output,
    PacketSequenceCandidate,
    RuleSetCandidate,
    CriticResult,
)
from sagefuzz_seedgen.tools.context_registry import set_program_context


TASKS: Dict[str, Dict[str, str]] = {
    "firewall": {
        "run_id": "2026-03-07T064109Z",
        "bmv2_json": "P4/firewall/build/firewall.json",
        "graphs_dir": "P4/firewall/build/graphs",
        "p4info": "P4/firewall/build/firewall.p4.p4info.txtpb",
        "topology": "P4/firewall/pod-topo/topology.json",
        "p4_source": "P4/firewall/solution/firewall.p4",
    },
    "link_monitor": {
        "run_id": "2026-03-07T070712Z",
        "bmv2_json": "P4/link_monitor/build/link_monitor.json",
        "graphs_dir": "P4/link_monitor/build/graphs",
        "p4info": "P4/link_monitor/build/link_monitor.p4.p4info.txtpb",
        "topology": "P4/link_monitor/pod-topo/topology.json",
        "p4_source": "P4/link_monitor/solution/link_monitor.p4",
    },
    "fast_reroute": {
        "run_id": "2026-03-07T053017Z",
        "bmv2_json": "P4/Fast-Reroute/build/fast_reroute.json",
        "graphs_dir": "P4/Fast-Reroute/build/graphs",
        "p4info": "P4/Fast-Reroute/build/fast_reroute.p4.p4info.txt",
        "topology": "P4/Fast-Reroute/p4app.json",
        "p4_source": "P4/Fast-Reroute/p4src/fast_reroute.p4",
    },
}


def _read_small_model() -> ModelConfig:
    lines = (ROOT / "tests" / "test_littlellm.py").read_text(encoding="utf-8").splitlines()

    def capture(name: str) -> str:
        pattern = re.compile(rf'{name}\s*=\s*"([^"]+)"')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = pattern.search(stripped)
            if match:
                return match.group(1)
        raise RuntimeError(f"Unable to parse active {name} from test_littlellm.py")

    return ModelConfig(
        model_id=os.getenv("POINT2_MODEL_ID") or capture("id"),
        api_key=os.getenv("POINT2_API_KEY") or capture("api_key"),
        base_url=os.getenv("POINT2_BASE_URL") or capture("base_url"),
        timeout_seconds=60.0,
        max_retries=1,
    )


def _first_match(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matching {pattern} under {directory}")
    return matches[0]


def _sample_path(task_name: str, agent_key: str) -> Path:
    run_dir = ROOT / "runs" / "agent_responses" / TASKS[task_name]["run_id"]
    mapping = {
        "agent1": run_dir / "agent1_semantic_analyzer" / "agent1_output_01.json",
        "agent2": run_dir / "agent2_sequence_constructor" / "packet_sequence_candidate_01.json",
        "agent4": _first_match(run_dir / "agent4_entity_generator", "entity_candidate_*_01.json"),
        "agent5": _first_match(run_dir / "agent5_entity_critic", "entity_critic_result_*_01.json"),
    }
    return mapping[agent_key]


def _schema_for(agent_key: str):
    return {
        "agent1": Agent1Output,
        "agent2": PacketSequenceCandidate,
        "agent4": RuleSetCandidate,
        "agent5": CriticResult,
    }[agent_key]


def _prompt_for(agent_key: str, model_input: Dict[str, Any]) -> str:
    if agent_key == "agent1":
        return (
            "You are Agent1. Here is the user_intent JSON (may be null). "
            "If missing required information, ask questions.\n\n"
            + json.dumps(model_input, ensure_ascii=False, indent=2)
        )
    if agent_key == "agent2":
        return "Generate PacketSequenceCandidate STRICT JSON. Input:\n\n" + json.dumps(
            model_input, ensure_ascii=False, indent=2
        )
    if agent_key == "agent4":
        return "Generate RuleSetCandidate STRICT JSON. Input:\n\n" + json.dumps(
            model_input, ensure_ascii=False, indent=2
        )
    if agent_key == "agent5":
        return "Evaluate control-plane entities and return CriticResult STRICT JSON:\n\n" + json.dumps(
            model_input, ensure_ascii=False, indent=2
        )
    raise ValueError(f"Unsupported agent key: {agent_key}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: replay_point2_single_sample.py <task_name> <agent_key>")
    task_name, agent_key = sys.argv[1], sys.argv[2]
    task = TASKS[task_name]
    sample_path = _sample_path(task_name, agent_key)
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    model_input = payload["input"]

    ctx = initialize_program_context(
        bmv2_json_path=ROOT / task["bmv2_json"],
        graphs_dir=ROOT / task["graphs_dir"],
        p4info_path=ROOT / task["p4info"],
        topology_path=ROOT / task["topology"],
        p4_source_path=ROOT / task["p4_source"],
    )
    set_program_context(ctx)

    small_model = _read_small_model()
    agent1, agent2, _agent3, agent4, agent5, _agent6, _ = build_agents_and_team(
        model_cfg=small_model,
        prompts_dir=ROOT / "prompts",
    )
    agent = {
        "agent1": agent1,
        "agent2": agent2,
        "agent4": agent4,
        "agent5": agent5,
    }[agent_key]

    prompt = _prompt_for(agent_key, model_input)
    schema = _schema_for(agent_key)
    result: Dict[str, Any] = {
        "task": task_name,
        "agent": agent_key,
        "sample_path": str(sample_path.relative_to(ROOT)),
        "model_id": small_model.model_id,
    }
    start = time.perf_counter()
    try:
        response = agent.run(prompt, output_schema=schema)
        content = response.content
        if isinstance(content, schema):
            content = content.model_dump()
            result["status"] = "success"
            result["content"] = content
        else:
            if hasattr(content, "model_dump"):
                content = content.model_dump()
            result["status"] = "invalid_output"
            result["content"] = content
    except Exception as exc:
        result["status"] = "error"
        result["error_type"] = exc.__class__.__name__
        result["error"] = str(exc)
    result["duration_seconds_wall"] = time.perf_counter() - start

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
