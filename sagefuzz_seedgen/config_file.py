from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_config_file(path: Path) -> Dict[str, Any]:
    """Load a seedgen config file (yaml/yml/json).

    This is intentionally small and permissive:
    - returns {} if file is empty
    - raises if format is unsupported or parsing fails
    """

    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}

    if suffix == ".json":
        data = json.loads(raw)
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception as e:
            raise RuntimeError("YAML config requires PyYAML installed.") from e
        data = yaml.safe_load(raw)
    else:
        raise ValueError(f"Unsupported config format: {suffix} (expected .yaml/.yml/.json)")

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping/object.")
    return data


def find_default_config_file() -> Path | None:
    for name in ("seedgen_config.yaml", "seedgen_config.yml", "seedgen_config.json"):
        p = Path(name)
        if p.exists():
            return p
    return None

