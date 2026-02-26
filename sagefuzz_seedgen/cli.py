from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from sagefuzz_seedgen.config import ModelConfig, ProgramPaths, RunConfig
from sagefuzz_seedgen.workflow.packet_sequence_workflow import run_packet_sequence_generation


def _path(p: str) -> Path:
    return Path(p)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="SageFuzz seed generation: packet_sequence stage (multi-agent)")

    ap.add_argument("--bmv2-json", type=_path, default=Path("P4/firewall/build/firewall.json"))
    ap.add_argument("--graphs-dir", type=_path, default=Path("P4/firewall/build/graphs"))
    ap.add_argument("--p4info", type=_path, default=Path("P4/firewall/build/firewall.p4.p4info.txtpb"))
    ap.add_argument("--topology", type=_path, default=Path("P4/firewall/pod-topo/topology.json"))

    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--out", type=_path, default=None)
    ap.add_argument("--session-state", type=_path, default=Path("runs/session_state.json"))

    ap.add_argument("--model-id", type=str, default=None)
    ap.add_argument("--api-key", type=str, default=None)
    ap.add_argument("--base-url", type=str, default=None)

    return ap


def main(argv: Optional[list[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    env_model = ModelConfig.from_env()
    model = ModelConfig(
        model_id=args.model_id or env_model.model_id,
        api_key=args.api_key or env_model.api_key,
        base_url=args.base_url or env_model.base_url,
    )

    program = ProgramPaths(
        bmv2_json=args.bmv2_json,
        graphs_dir=args.graphs_dir,
        p4info_txtpb=args.p4info,
        topology_json=args.topology,
    )

    cfg = RunConfig(
        program=program,
        model=model,
        max_retries=args.max_retries,
        out_path=args.out,
        session_state_path=args.session_state,
    )

    out = run_packet_sequence_generation(cfg)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

