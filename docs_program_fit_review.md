# Multi-Program Fit Review

This document records the human-style intents used to exercise the system against multiple P4 programs, plus the generated output locations and review status.

## Programs
- firewall
- link_monitor
- Heavy_Hitter_Detector
- Fast-Reroute
- Congestion_Aware_Load_Balancing

## Review Entries

### Heavy_Hitter_Detector
- Intent:
  - 验证 heavy hitter 检测功能。可以在测试前由人工把交换机的阈值临时调低到 10。然后让 h1 向 h2 发送同一条五元组 TCP 流，期望前 10 个包可以转发，第 11 个及之后的包被丢弃；另外再生成一个不同五元组的新 TCP 流，期望它不受前一条流影响。
- Output index:
  - runs/2026-03-07T041513Z_packet_sequence_index.json
- Testcase dir:
  - runs/2026-03-07T041513Z_testcases
- Output cases:
  - runs/2026-03-07T041513Z_testcases/positive_heavy_hitter_triggered.json
  - runs/2026-03-07T041513Z_testcases/positive_new_flow_unaffected.json
- Status:
  - PASS
- Notes:
  - Uses manual threshold override expressed via `operator_actions`.
  - Packet sequence, oracle prediction, and final testcase generation all succeeded.
  - Baseline forwarding entities were supplied by deterministic minimal fallback when Agent4 returned empty entities.

### Fast-Reroute
- Intent:
  - 验证 fast reroute 功能。让 h2 到 h4 发送 IPv4 流量；测试过程中人工将 s1-s2 这条链路断开，期望流量先立即切换到备份路径；然后人工通知控制器重收敛，期望流量切换到新的最短路径。
- Output index:
  - runs/2026-03-07T051823Z_packet_sequence_index.json
- Testcase dir:
  - runs/2026-03-07T051823Z_testcases
- Output cases:
  - runs/2026-03-07T051823Z_testcases/baseline_forwarding.json
  - runs/2026-03-07T051823Z_testcases/fast_reroute_after_link_failure.json
  - runs/2026-03-07T051823Z_testcases/convergence_to_new_shortest_path.json
- Status:
  - PASS
- Notes:
  - Uses manual link-failure and controller-notify operator actions.
  - Packet sequence, oracle prediction, and final testcase generation all succeeded.
  - Baseline forwarding entities were supplied by deterministic minimal fallback when Agent4 returned invalid or empty entities.

### Congestion_Aware_Load_Balancing
- Intent:
  - 验证拥塞感知负载均衡功能。让 h1 到 h5 发送多条 TCP 流，期望这些流可以分散到不同路径；如果某条路径拥塞，后续流量应该切换到其他路径。
- Output index:
  - runs/2026-03-07T063623Z_packet_sequence_index.json
- Testcase dir:
  - runs/2026-03-07T063623Z_testcases
- Output cases:
  - runs/2026-03-07T063623Z_testcases/baseline_load_distribution.json
  - runs/2026-03-07T063623Z_testcases/congestion_reroute.json
- Status:
  - PASS
- Notes:
  - Uses deterministic packet-sequence repair and deterministic minimal forwarding fallback to stabilize generation.
  - Operator actions and observation requirements were inferred from the human intent to express congestion injection and path-utilization checks.

### firewall
- Intent:
  - 验证有状态防火墙功能。h1 和 h2 是内部主机，其他是外部主机。要求内部主机主动向外部主机发起连接时允许通信，外部主机主动发起到内部时不允许。
- Output index:
  - runs/2026-03-07T064109Z_packet_sequence_index.json
- Testcase dir:
  - runs/2026-03-07T064109Z_testcases
- Output cases:
  - runs/2026-03-07T064109Z_testcases/positive_internal_initiates.json
  - runs/2026-03-07T064109Z_testcases/negative_external_initiates.json
- Status:
  - PASS
- Notes:
  - Regression revalidated successfully after the generalized multi-program changes.

### link_monitor
- Intent:
  - 验证链路利用率监控功能。选择 h1 到 h3 通信路径上的任意一条链路作为监控对象，使用程序已有的 probe 探测包从 h1 发送到 h3，配合持续流量至少 20 个包来触发可观测的链路利用率变化。只需要一个正向场景，成功标准是 probe 回包或监控结果中能看到该链路的利用率数值大于 0。
- Output index:
  - runs/2026-03-07T070252Z_packet_sequence_index.json
- Testcase dir:
  - runs/2026-03-07T070252Z_testcases
- Output cases:
  - runs/2026-03-07T070252Z_testcases/link_utilization_monitoring_positive.json
- Status:
  - PASS
- Notes:
  - Regression revalidated successfully using the program-defined probe path and probe-response observation semantics.
