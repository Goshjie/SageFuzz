from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AgentRecorder:
    """Persist per-agent inputs/outputs for review.

    Directory layout:
      runs/agent_responses/<run_id>/<agent_role>/<step>_<round>.json
    """

    base_dir: Path
    run_id: str

    def _agent_dir(self, agent_role: str) -> Path:
        return self.base_dir / "agent_responses" / self.run_id / agent_role

    def record(
        self,
        *,
        agent_role: str,
        step: str,
        round_id: int,
        model_input: Any,
        model_output: Any,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Path:
        out_dir = self._agent_dir(agent_role)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{step}_{round_id:02d}.json"

        payload: Dict[str, Any] = {
            "agent_role": agent_role,
            "step": step,
            "round": round_id,
            "input": model_input,
            "output": model_output,
        }
        if extra:
            payload["extra"] = extra

        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return out_path

