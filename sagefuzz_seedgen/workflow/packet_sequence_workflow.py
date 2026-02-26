from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sagefuzz_seedgen.agents.team_factory import build_agents_and_team
from sagefuzz_seedgen.config import RunConfig
from sagefuzz_seedgen.runtime.initializer import initialize_program_context
from sagefuzz_seedgen.schemas import (
    AttemptResult,
    PacketSequenceCandidate,
    TaskSpec,
    TestcaseOutput,
    TopologySummary,
)
from sagefuzz_seedgen.tools.context_registry import set_program_context
from sagefuzz_seedgen.topology.topology_loader import summarize_topology
from sagefuzz_seedgen.workflow.validation import validate_directional_tcp_state_trigger


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _load_json_file(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def _write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def run_packet_sequence_generation(cfg: RunConfig) -> Path:
    ctx = initialize_program_context(
        bmv2_json_path=cfg.program.bmv2_json,
        graphs_dir=cfg.program.graphs_dir,
        p4info_path=cfg.program.p4info_txtpb,
        topology_path=cfg.program.topology_json,
    )
    set_program_context(ctx)

    session_state_path = cfg.session_state_path or Path("runs/session_state.json")
    session_state = _load_json_file(session_state_path)
    session_state.setdefault("run_config", {})
    session_state["run_config"].update(
        {
            "max_retries": cfg.max_retries,
            "bmv2_json": str(cfg.program.bmv2_json),
            "graphs_dir": str(cfg.program.graphs_dir),
            "p4info": str(cfg.program.p4info_txtpb),
            "topology": str(cfg.program.topology_json),
        }
    )

    if cfg.model is None:
        raise ValueError("ModelConfig is required to run agents.")

    agent1, agent2, _agent3, team = build_agents_and_team(model_cfg=cfg.model, prompts_dir=Path("prompts"))

    # --- Step 1: Semantic analyzer produces a task spec ---
    task: TaskSpec = agent1.run(
        "Generate one TaskSpec for a directional stateful firewall test (internal initiates, external replies).",
        output_schema=TaskSpec,
        session_state=session_state,
    ).content  # type: ignore[assignment]

    # Ensure defaults are present for this program if agent returns empty/unknown.
    if not task.internal_host:
        task.internal_host = cfg.default_internal_host  # type: ignore[misc]
    if not task.external_host:
        task.external_host = cfg.default_external_host  # type: ignore[misc]

    last_feedback: Optional[str] = None
    last_attempt: Optional[AttemptResult] = None
    attempt_count: int = 0

    # --- Step 2: Generate packet_sequence with critic loop ---
    for attempt in range(1, cfg.max_retries + 1):
        attempt_count = attempt
        prompt = {
            "attempt": attempt,
            "task": task.model_dump(),
            "previous_feedback": last_feedback,
            "requirements": {
                "must_include_tx_host": True,
                "positive_handshake_required": True,
                "negative_external_initiation_optional": task.include_negative_external_initiation,
            },
        }

        try:
            # Preferred: use Team so the leader can coordinate member interactions.
            run_out = team.run(
                {
                    "instruction": (
                        "Coordinate the team to produce an AttemptResult JSON. "
                        "Ask Sequence Constructor to generate packet_sequence, then ask Constraint Critic to evaluate it. "
                        "Return {task_id, packet_sequence, critic:{status,feedback}} only."
                    ),
                    "input": prompt,
                },
                output_schema=AttemptResult,
                session_state=session_state,
                yield_run_output=True,
            )
            # Team.run may return TeamRunOutput if yield_run_output=True; normalize.
            content = getattr(run_out, "content", None)
            if isinstance(content, AttemptResult):
                attempt_result = content
            else:
                # Fallback: try parsing if content is a dict
                attempt_result = AttemptResult.model_validate(content)
        except Exception:
            # Fallback path: call the generator agent directly and use deterministic validator.
            cand_out = agent2.run(
                {
                    "task": task.model_dump(),
                    "previous_feedback": last_feedback,
                },
                output_schema=PacketSequenceCandidate,
                session_state=session_state,
            )
            candidate: PacketSequenceCandidate = cand_out.content  # type: ignore[assignment]
            critic = validate_directional_tcp_state_trigger(ctx=ctx, task=task, packet_sequence=candidate.packet_sequence)
            attempt_result = AttemptResult(task_id=task.task_id, packet_sequence=candidate.packet_sequence, critic=critic)

        # Always run deterministic validator as the ground truth for this stage's DoD.
        det = validate_directional_tcp_state_trigger(ctx=ctx, task=task, packet_sequence=attempt_result.packet_sequence)
        if det.status == "FAIL":
            attempt_result.critic = det

        last_attempt = attempt_result
        last_feedback = attempt_result.critic.feedback

        if attempt_result.critic.status == "PASS":
            break

    if last_attempt is None:
        raise RuntimeError("No attempt was executed.")

    topo = summarize_topology(ctx.topology)
    topo_summary = TopologySummary(hosts=topo["hosts"], links=topo["links"])

    output = TestcaseOutput(
        program=ctx.program_name or "unknown",
        topology_ref=str(ctx.topology_path),
        topology=topo_summary,
        task_id=task.task_id,
        packet_sequence=last_attempt.packet_sequence,
        meta={
            "generator": "sagefuzz_seedgen",
            "timestamp_utc": _utc_ts(),
            "attempts": attempt_count,
            "final_status": last_attempt.critic.status,
            "final_feedback": last_attempt.critic.feedback,
        },
    )

    out_path = cfg.out_path or Path("runs") / f"{_utc_ts()}_packet_sequence.json"
    _write_json_file(out_path, output.model_dump())
    _write_json_file(session_state_path, session_state)

    return out_path
