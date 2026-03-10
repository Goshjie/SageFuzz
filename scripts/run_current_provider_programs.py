from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagefuzz_seedgen.config_file import load_config_file


@dataclass(frozen=True)
class ProgramRun:
    name: str
    intent: Dict[str, Any]
    paths: Dict[str, str]
    max_retries: int = 5


PROGRAMS: List[ProgramRun] = [
    ProgramRun(
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
    ProgramRun(
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
    ProgramRun(
        name="heavy_hitter",
        intent={
            "intent_text": "验证 heavy hitter 检测功能。可以在测试前由人工把交换机的阈值临时调低到 10。然后让 h1 向 h2 发送同一条五元组 TCP 流，期望前 10 个包可以转发，第 11 个及之后的包被丢弃；另外再生成一个不同五元组的新 TCP 流，期望它不受前一条流影响。",
            "feature_under_test": "forwarding_behavior",
            "topology_mapping": "测试 h1 到 h2 的 TCP 流量行为，并比较同一五元组与不同五元组的差异。",
            "operator_constraints": "测试前允许人工将阈值临时调低到 10。",
            "traffic_pattern": "先发送一条重复五元组 TCP 流，再发送一条不同五元组的新 TCP 流。",
            "include_negative_case": True,
            "test_objective": "data_plane_behavior",
        },
        paths={
            "bmv2_json": "P4/Heavy_Hitter_Detector/build/heavy_hitter.json",
            "graphs_dir": "P4/Heavy_Hitter_Detector/build/graphs",
            "p4info": "P4/Heavy_Hitter_Detector/build/heavy_hitter.p4.p4info.txt",
            "topology": "P4/Heavy_Hitter_Detector/p4app.json",
            "p4_source": "P4/Heavy_Hitter_Detector/solution/heavy_hitter.p4",
        },
    ),
    ProgramRun(
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
    ProgramRun(
        name="load_balancer",
        intent={
            "intent_text": "验证拥塞感知负载均衡功能。让 h1 到 h5 发送多条 TCP 流，期望这些流可以分散到不同路径；如果某条路径拥塞，后续流量应该切换到其他路径。",
            "feature_under_test": "forwarding_behavior",
            "topology_mapping": "关注 h1 到 h5 的多路径转发与拥塞后的路径切换。",
            "observation_target": "不同路径上的负载分布和拥塞后的后续路径选择",
            "expected_observation": "在基线阶段多条流分散到不同路径；发生拥塞后，后续流量切换到其他可用路径。",
            "traffic_pattern": "发送多条 TCP 流，覆盖正常分流和拥塞后重分流两个阶段。",
            "include_negative_case": False,
            "test_objective": "data_plane_behavior",
        },
        paths={
            "bmv2_json": "P4/Congestion_Aware_Load_Balancing/build/loadbalancer.json",
            "graphs_dir": "P4/Congestion_Aware_Load_Balancing/build/graphs",
            "p4info": "P4/Congestion_Aware_Load_Balancing/build/loadbalancer.p4.p4info.txt",
            "topology": "P4/Congestion_Aware_Load_Balancing/topology.json",
            "p4_source": "P4/Congestion_Aware_Load_Balancing/p4src/loadbalancer.p4",
        },
    ),
]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _latest_index_files() -> set[str]:
    return {str(p) for p in (ROOT / "runs").glob("*_packet_sequence_index.json")}


def _extract_index_path(stdout: str, before: set[str]) -> Optional[Path]:
    import re

    match = re.findall(r"runs/[^\s]+_packet_sequence_index\.json", stdout)
    if match:
        return ROOT / match[-1]
    after = _latest_index_files()
    created = sorted(after - before)
    if created:
        return ROOT / created[-1]
    return None


def _load_model_section() -> Dict[str, Any]:
    cfg = load_config_file(ROOT / "seedgen_config.yaml")
    model = cfg.get("model")
    if not isinstance(model, dict):
        raise RuntimeError("seedgen_config.yaml is missing a valid model section.")
    return model


def main() -> int:
    model = _load_model_section()
    timeout_seconds = int(model.get("timeout_seconds", 120))
    max_retries = int(model.get("max_retries", 3))
    run_timeout = int((timeout_seconds + 30) * max_retries * 8)

    out_dir = ROOT / "runs" / f"current_provider_programs_{_utc_ts()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "configs").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)

    selected = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    results: List[Dict[str, Any]] = []
    for program in PROGRAMS:
        if selected is not None and program.name not in selected:
            continue
        config = {
            "model": dict(model),
            "intent": dict(program.intent),
            "run": {"max_retries": program.max_retries},
            "paths": dict(program.paths),
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
        cfg_path = out_dir / "configs" / f"{program.name}.json"
        cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        before = _latest_index_files()
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(ROOT / ".venv" / "bin" / "python"), "-m", "sagefuzz_seedgen.cli", "--config", str(cfg_path)],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=run_timeout,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Timed out after {run_timeout} seconds.\n",
            )
            timed_out = True
        duration = time.perf_counter() - start

        stdout_log = out_dir / "logs" / f"{program.name}.stdout.log"
        stderr_log = out_dir / "logs" / f"{program.name}.stderr.log"
        stdout_log.write_text(completed.stdout, encoding="utf-8")
        stderr_log.write_text(completed.stderr, encoding="utf-8")

        index_path = _extract_index_path(completed.stdout, before)
        summary: Dict[str, Any] = {}
        if index_path is not None and index_path.exists():
            summary = json.loads(index_path.read_text(encoding="utf-8")).get("summary", {})

        row = {
            "program": program.name,
            "returncode": completed.returncode,
            "timed_out": timed_out,
            "duration_seconds_wall": duration,
            "index_path": str(index_path.relative_to(ROOT)) if index_path and index_path.exists() else None,
            "summary": {
                "program": summary.get("program"),
                "task_id": summary.get("task_id"),
                "final_status": summary.get("final_status"),
                "packet_sequence_status": summary.get("packet_sequence_status"),
                "final_feedback": summary.get("final_feedback"),
                "attempts_packet_sequence": summary.get("attempts_packet_sequence"),
                "passed_case_count": summary.get("passed_case_count"),
                "failed_case_count": summary.get("failed_case_count"),
                "oracle_prediction_fallback_case_count": summary.get("oracle_prediction_fallback_case_count"),
            },
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    payload = {
        "model": {
            "model_id": model.get("model_id"),
            "base_url": model.get("base_url"),
        },
        "results": results,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Current Provider Full-Program Results",
        "",
        f"- `model_id`: `{model.get('model_id')}`",
        f"- `base_url`: `{model.get('base_url')}`",
        "",
        "| Program | Return | TimedOut | Final | PacketSeq | Attempts | Passed | Failed | OracleFallback | Wall(s) | Index |",
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        s = item["summary"]
        lines.append(
            "| {program} | {returncode} | {timed_out} | {final_status} | {packet_status} | {attempts} | {passed} | {failed} | {oracle_fallback} | {wall:.2f} | `{index}` |".format(
                program=item["program"],
                returncode=item["returncode"],
                timed_out=item["timed_out"],
                final_status=s.get("final_status"),
                packet_status=s.get("packet_sequence_status"),
                attempts=s.get("attempts_packet_sequence"),
                passed=s.get("passed_case_count"),
                failed=s.get("failed_case_count"),
                oracle_fallback=s.get("oracle_prediction_fallback_case_count"),
                wall=item["duration_seconds_wall"],
                index=item["index_path"],
            )
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[current-provider] results saved to {out_dir.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
