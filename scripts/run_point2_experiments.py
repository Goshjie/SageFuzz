from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class TaskDef:
    name: str
    intent: Dict[str, Any]
    paths: Dict[str, str]
    max_retries: int = 4


TASKS: List[TaskDef] = [
    TaskDef(
        name="firewall",
        intent={
            "intent_text": "验证有状态防火墙功能。h1 和 h2 是内部主机，其他是外部主机。要求内部主机主动向外部主机发起连接时允许通信，外部主机主动发起到内部时不允许。",
            "feature_under_test": "policy_validation",
            "topology_zone_mapping": "h1 和 h2 是 internal，h3 是 external。",
            "role_policy": "仅允许 internal 主动向 external 发起 TCP 连接；external 只能回复已建立连接，不能主动发起。",
            "include_negative_case": True,
            "test_objective": "data_plane_behavior",
        },
        paths={
            "bmv2_json": "P4/firewall/build/firewall.json",
            "graphs_dir": "P4/firewall/build/graphs",
            "p4info": "P4/firewall/build/firewall.p4.p4info.txtpb",
            "topology": "P4/firewall/pod-topo/topology.json",
            "p4_source": "P4/firewall/solution/firewall.p4",
        },
    ),
    TaskDef(
        name="link_monitor",
        intent={
            "intent_text": "验证链路利用率监控功能。选择 h1 到 h3 通信路径上的任意一条链路作为监控对象，使用程序已有的 probe 探测包从 h1 发送到 h3，配合持续流量至少 20 个包来触发可观测的链路利用率变化。只需要一个正向场景，成功标准是 probe 回包或监控结果中能看到该链路的利用率数值大于 0。",
            "feature_under_test": "traffic_monitoring",
            "topology_mapping": "关注 h1 到 h3 的通信路径，监控对象为该路径上的任意一条链路。",
            "observation_target": "h1 到 h3 路径上一条被监控链路的利用率",
            "observation_method": "使用程序已有的 probe 探测包，并以 probe 回包或监控结果作为观测依据。",
            "expected_observation": "在持续业务流量驱动后，观测到的链路利用率数值应大于 0。",
            "traffic_pattern": "先发送至少 20 个包的持续流量，再发送 probe 相关探测包。",
            "include_negative_case": False,
            "test_objective": "data_plane_behavior",
        },
        paths={
            "bmv2_json": "P4/link_monitor/build/link_monitor.json",
            "graphs_dir": "P4/link_monitor/build/graphs",
            "p4info": "P4/link_monitor/build/link_monitor.p4.p4info.txtpb",
            "topology": "P4/link_monitor/pod-topo/topology.json",
            "p4_source": "P4/link_monitor/solution/link_monitor.p4",
        },
    ),
    TaskDef(
        name="fast_reroute",
        intent={
            "intent_text": "验证 fast reroute 功能。让 h2 到 h4 发送 IPv4 流量；测试过程中人工将 s1-s2 这条链路断开，期望流量先立即切换到备份路径；然后人工通知控制器重收敛，期望流量切换到新的最短路径。",
            "feature_under_test": "forwarding_behavior",
            "topology_mapping": "测试 h2 到 h4 的转发路径，重点关注 s1-s2 链路失效前后的路径切换。",
            "operator_constraints": "测试过程中人工执行两步操作：先断开 s1-s2 链路，再人工通知控制器执行重收敛。",
            "traffic_pattern": "持续发送 h2 到 h4 的 IPv4 流量，覆盖链路失效前、失效后和控制器通知后的阶段。",
            "include_negative_case": False,
            "test_objective": "data_plane_behavior",
        },
        paths={
            "bmv2_json": "P4/Fast-Reroute/build/fast_reroute.json",
            "graphs_dir": "P4/Fast-Reroute/build/graphs",
            "p4info": "P4/Fast-Reroute/build/fast_reroute.p4.p4info.txt",
            "topology": "P4/Fast-Reroute/p4app.json",
            "p4_source": "P4/Fast-Reroute/p4src/fast_reroute.p4",
        },
    ),
]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _slugify_model_id(model_id: Any) -> str:
    raw = str(model_id or "unknown-model").strip().lower()
    raw = raw.replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw).strip("._-") or "unknown-model"


def _read_baseline_model() -> Dict[str, Any]:
    small = _read_small_model()
    return {
        "model_id": "qwen-plus",
        "api_key": small.get("api_key"),
        "base_url": small.get("base_url"),
        "timeout_seconds": 120.0,
        "max_retries": 2,
    }


def _read_small_model() -> Dict[str, Any]:
    script_path = ROOT / "tests" / "test_littlellm.py"
    lines = script_path.read_text(encoding="utf-8").splitlines()

    def capture(name: str) -> str:
        pattern = re.compile(rf'{name}\s*=\s*"([^"]+)"')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = pattern.search(stripped)
            if match:
                return match.group(1)
        raise RuntimeError(f"Unable to parse active {name} from {script_path}")

    return {
        "model_id": os.getenv("POINT2_MODEL_ID") or capture("id"),
        "api_key": os.getenv("POINT2_API_KEY") or capture("api_key"),
        "base_url": os.getenv("POINT2_BASE_URL") or capture("base_url"),
        "timeout_seconds": 120.0,
        "max_retries": 2,
    }


def _latest_index_files() -> set[str]:
    return {str(p) for p in RUNS_DIR.glob("*_packet_sequence_index.json")}


def _extract_index_path(stdout: str, before: set[str]) -> Optional[Path]:
    match = re.findall(r"runs/[^\s]+_packet_sequence_index\.json", stdout)
    if match:
        return ROOT / match[-1]

    after = _latest_index_files()
    created = sorted(after - before)
    if created:
        return ROOT / created[-1]
    return None


def _sanitize_model(model: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "model_id": model.get("model_id"),
        "base_url": model.get("base_url"),
        "timeout_seconds": model.get("timeout_seconds"),
        "max_retries": model.get("max_retries"),
    }


def _build_config(
    *,
    task: TaskDef,
    baseline_model: Dict[str, Any],
    small_model: Dict[str, Any],
    mode: str,
) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "model": dict(baseline_model),
        "intent": dict(task.intent),
        "run": {"max_retries": task.max_retries},
        "paths": dict(task.paths),
        "memory": {
            "enabled": True,
            "db_path": "runs/agno_memory.db",
            "user_id": "sagefuzz-local-user",
            "update_memory_on_run": True,
            "add_memories_to_context": True,
            "enable_session_summaries": False,
            "add_session_summary_to_context": False,
        },
    }
    if mode == "agent5_small":
        config["agent_models"] = {"agent5": dict(small_model)}
    elif mode == "all_small":
        config["agent_models"] = {"all_agents": dict(small_model)}
    elif mode != "baseline":
        raise ValueError(f"Unsupported mode: {mode}")
    return config


def _run_one(
    *,
    task: TaskDef,
    mode: str,
    experiment_dir: Path,
    baseline_model: Dict[str, Any],
    small_model: Dict[str, Any],
) -> Dict[str, Any]:
    config = _build_config(
        task=task,
        baseline_model=baseline_model,
        small_model=small_model,
        mode=mode,
    )
    config_dir = experiment_dir / "configs"
    logs_dir = experiment_dir / "logs"
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = config_dir / f"{task.name}__{mode}.json"
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cmd = [str(ROOT / ".venv" / "bin" / "python"), "-m", "sagefuzz_seedgen.cli", "--config", str(cfg_path)]
    before = _latest_index_files()
    start = time.perf_counter()
    timeout_seconds = int(os.getenv("POINT2_RUN_TIMEOUT", "900"))
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            args=cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Timed out after {timeout_seconds} seconds.\n",
        )
        timed_out = True
    duration = time.perf_counter() - start

    (logs_dir / f"{task.name}__{mode}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (logs_dir / f"{task.name}__{mode}.stderr.log").write_text(completed.stderr, encoding="utf-8")

    index_path = _extract_index_path(completed.stdout, before)
    index_payload: Optional[Dict[str, Any]] = None
    summary: Dict[str, Any] = {}
    if index_path is not None and index_path.exists():
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        summary = dict(index_payload.get("summary", {}))

    return {
        "task": task.name,
        "mode": mode,
        "returncode": completed.returncode,
        "timed_out": timed_out,
        "duration_seconds_wall": duration,
        "stdout_log": str((logs_dir / f"{task.name}__{mode}.stdout.log").relative_to(ROOT)),
        "stderr_log": str((logs_dir / f"{task.name}__{mode}.stderr.log").relative_to(ROOT)),
        "index_path": str(index_path.relative_to(ROOT)) if index_path is not None and index_path.exists() else None,
        "summary": {
            "program": summary.get("program"),
            "task_id": summary.get("task_id"),
            "final_status": summary.get("final_status"),
            "packet_sequence_status": summary.get("packet_sequence_status"),
            "attempts_packet_sequence": summary.get("attempts_packet_sequence"),
            "passed_case_count": summary.get("passed_case_count"),
            "failed_case_count": summary.get("failed_case_count"),
            "oracle_prediction_fallback_case_count": summary.get("oracle_prediction_fallback_case_count"),
        },
        "artifacts": index_payload.get("artifacts", {}) if index_payload else {},
    }


def _write_markdown_summary(
    *,
    experiment_dir: Path,
    baseline_model: Dict[str, Any],
    small_model: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> None:
    lines = [
        "# Point-2 Experiment Results",
        "",
        f"- `baseline_model`: `{_sanitize_model(baseline_model)}`",
        f"- `small_model`: `{_sanitize_model(small_model)}`",
        "",
        "| Task | Mode | Return | Final | PacketSeq | Attempts | Passed | Failed | OracleFallback | Wall(s) | Index |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        summary = item.get("summary", {})
        lines.append(
            "| {task} | {mode} | {returncode} | {final_status} | {packet_sequence_status} | {attempts} | {passed} | {failed} | {oracle_fallback} | {wall:.2f} | `{index}` |".format(
                task=item["task"],
                mode=item["mode"],
                returncode=item["returncode"],
                final_status=summary.get("final_status"),
                packet_sequence_status=summary.get("packet_sequence_status"),
                attempts=summary.get("attempts_packet_sequence"),
                passed=summary.get("passed_case_count"),
                failed=summary.get("failed_case_count"),
                oracle_fallback=summary.get("oracle_prediction_fallback_case_count"),
                wall=item["duration_seconds_wall"],
                index=item.get("index_path"),
            )
        )
    (experiment_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    baseline_model = _read_baseline_model()
    small_model = _read_small_model()

    experiment_dir = RUNS_DIR / f"point2_experiments__{_slugify_model_id(small_model.get('model_id'))}__{_utc_ts()}"
    experiment_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for task in TASKS:
        for mode in ("baseline", "agent5_small", "all_small"):
            print(f"[point2] running task={task.name} mode={mode}", flush=True)
            result = _run_one(
                task=task,
                mode=mode,
                experiment_dir=experiment_dir,
                baseline_model=baseline_model,
                small_model=small_model,
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "task": task.name,
                        "mode": mode,
                        "returncode": result["returncode"],
                        "summary": result["summary"],
                        "index_path": result["index_path"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    payload = {
        "experiment_dir": str(experiment_dir.relative_to(ROOT)),
        "baseline_model": _sanitize_model(baseline_model),
        "small_model": _sanitize_model(small_model),
        "results": results,
    }
    (experiment_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown_summary(
        experiment_dir=experiment_dir,
        baseline_model=baseline_model,
        small_model=small_model,
        results=results,
    )
    print(f"[point2] results saved to {experiment_dir.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
