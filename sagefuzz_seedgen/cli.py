from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from sagefuzz_seedgen.config import ModelConfig, ProgramPaths, RunConfig
from sagefuzz_seedgen.config_file import find_default_config_file, load_config_file


def _path(p: str) -> Path:
    return Path(p)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="SageFuzz seed generation: packet_sequence stage (multi-agent)")

    ap.add_argument(
        "--config",
        type=_path,
        default=None,
        help="Path to config file (yaml/yml/json). If omitted, auto-detect seedgen_config.{yaml,yml,json}.",
    )

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

    cfg_path = args.config
    if cfg_path is None:
        cfg_path = find_default_config_file()

    cfg_data = {}
    if cfg_path is not None:
        if not cfg_path.exists():
            raise SystemExit(f"Config file not found: {cfg_path}")
        cfg_data = load_config_file(cfg_path)

    model_section = cfg_data.get("model", {})
    if not isinstance(model_section, dict):
        model_section = {}

    intent_section = cfg_data.get("intent", {})
    if not isinstance(intent_section, dict):
        intent_section = {}

    env_model = ModelConfig.from_env()
    model = ModelConfig(
        model_id=args.model_id or model_section.get("model_id") or env_model.model_id,
        api_key=args.api_key or model_section.get("api_key") or env_model.api_key,
        base_url=args.base_url or model_section.get("base_url") or env_model.base_url,
    )

    # Optional: allow overriding paths/run config from config file while keeping CLI defaults.
    paths_section = cfg_data.get("paths", {})
    if not isinstance(paths_section, dict):
        paths_section = {}
    run_section = cfg_data.get("run", {})
    if not isinstance(run_section, dict):
        run_section = {}

    program = ProgramPaths(
        bmv2_json=_path(paths_section.get("bmv2_json")) if paths_section.get("bmv2_json") else args.bmv2_json,
        graphs_dir=_path(paths_section.get("graphs_dir")) if paths_section.get("graphs_dir") else args.graphs_dir,
        p4info_txtpb=_path(paths_section.get("p4info")) if paths_section.get("p4info") else args.p4info,
        topology_json=_path(paths_section.get("topology")) if paths_section.get("topology") else args.topology,
    )

    cfg = RunConfig(
        program=program,
        model=model,
        user_intent=intent_section or None,
        max_retries=int(run_section.get("max_retries")) if run_section.get("max_retries") else args.max_retries,
        out_path=args.out,
        session_state_path=args.session_state,
    )

    # Import lazily so `--help` works without model/provider deps.
    from sagefuzz_seedgen.workflow.packet_sequence_workflow import run_packet_sequence_generation

    out = run_packet_sequence_generation(cfg)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
