from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    api_key: str
    base_url: str

    @staticmethod
    def from_env(
        *,
        model_id_env: str = "AGNO_MODEL_ID",
        api_key_env: str = "AGNO_API_KEY",
        base_url_env: str = "AGNO_BASE_URL",
        default_model_id: str = "doubao-seed-2.0-code",
        default_base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3",
    ) -> "ModelConfig":
        model_id = getenv(model_id_env) or default_model_id
        api_key = getenv(api_key_env) or ""
        base_url = getenv(base_url_env) or default_base_url
        return ModelConfig(model_id=model_id, api_key=api_key, base_url=base_url)


@dataclass(frozen=True)
class ProgramPaths:
    bmv2_json: Path
    graphs_dir: Path
    p4info_txtpb: Path
    topology_json: Path


@dataclass(frozen=True)
class RunConfig:
    program: ProgramPaths
    model: Optional[ModelConfig]
    max_retries: int = 4
    out_path: Optional[Path] = None
    session_state_path: Optional[Path] = None

    # Topology defaults (can be inferred from topology.json; keep overrides for experiments)
    default_internal_host: str = "h1"
    default_external_host: str = "h3"
