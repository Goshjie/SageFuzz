# 当前 `seedgen_config.yaml` Provider 基线批量测试结果

本次测试直接使用 `seedgen_config.yaml` 中配置的原始 provider：

- `model_id`: `gpt-5.4`
- `base_url`: `https://api-vip.codex-for.me/v1`

为适配该 provider 对流式调用的要求，已在工作流中加入流式兼容处理。测试脚本为：

- `scripts/run_current_provider_programs.py`

结果目录：

- `runs/current_provider_programs_2026-03-10T073043Z`

## 1. 总体结果

| 程序 | 是否生成 testcase | 最终状态 | wall-clock 时间 | 备注 |
| --- | --- | --- | ---: | --- |
| firewall | 是 | PASS | 109.15 s | 生成 2 个 testcase，packet_sequence 与场景实体通过，但 oracle 使用 fallback |
| link_monitor | 否 | — | 16.44 s | `Agent1` 阶段多次连接错误，未生成 task |
| heavy_hitter | 否 | — | 16.41 s | `Agent1` 阶段多次连接错误，未生成 task |
| fast_reroute | 否 | — | 16.13 s | `Agent1` 阶段多次连接错误，未生成 task |
| load_balancer | 否 | — | 16.04 s | `Agent1` 阶段多次连接错误，未生成 task |

## 2. firewall 结果解释

`firewall` 是本轮中唯一成功生成完整 testcase 的程序，对应产物为：

- `runs/2026-03-10T073044Z_packet_sequence_index.json`
- `runs/2026-03-10T073044Z_testcases/positive_internal_initiated_tcp_connection.json`
- `runs/2026-03-10T073044Z_testcases/negative_external_initiated_tcp_connection.json`

从 `index.json` 的摘要看：

- `final_status = PASS`
- `packet_sequence_status = PASS`
- 生成了 1 个正向场景与 1 个负向场景

从 testcase 内容看，场景层面的语义与用户意图是对齐的：

- 正向场景：内部主机 `h1` 主动向外部主机 `h3` 发起 TCP 连接；
- 负向场景：外部主机 `h3` 主动向内部主机 `h1` 发起 TCP 连接；
- 控制面规则与执行顺序均已落盘；
- 两个 testcase 都生成成功。

但该结果仍存在两个局限：

1. 控制面实体最终依赖 deterministic fallback 生成，而不是完全由模型稳定生成；
2. oracle 阶段两条场景都使用了 fallback，因此“预期结果解释”层并不稳定。

因此，对 `firewall` 更准确的判断是：

> 当前 provider 可以在 `firewall` 场景上生成**基本符合意图**的 testcase，但 testcase 的某些部分仍依赖系统兜底，尤其是 oracle 预测部分还不够稳定。

## 3. 其余四个程序的失败原因

`link_monitor`、`heavy_hitter`、`fast_reroute`、`load_balancer` 都未生成 testcase。日志显示，它们的主要失败点都集中在 `Agent1` 阶段。

具体表现为：

- `Agent1` 在 schema 模式调用时反复出现 `Connection error`；
- 触发多轮重试后仍无法得到合法 `TaskSpec`；
- 随后流程退回问题收集分支；
- 由于当前是非交互批处理，最终报出：
  - `RuntimeError: Unable to obtain sufficient user intent to generate a task.`

这说明：

- 当前 provider 的流式兼容问题已经修复；
- 但在真实复杂意图规约阶段，provider 仍然存在稳定性不足；
- 因而当前配置**不能稳定支撑所有程序**的一轮完整生成。

## 4. 当前结论

基于这轮基线批量测试，可以得到以下结论：

1. 当前 `seedgen_config.yaml` 配置的 provider 已经可以在 `firewall` 上生成完整 testcase；
2. 生成出的 `firewall` testcase 在场景语义上基本符合用户意图；
3. 但生成结果仍部分依赖 fallback，尤其是 oracle 部分尚不稳定；
4. 对 `link_monitor`、`heavy_hitter`、`fast_reroute`、`load_balancer`，当前 provider 还不能稳定完成从意图到 testcase 的完整生成；
5. 因此，该 provider 当前更适合作为“可在部分程序上跑通”的基线，而不适合作为所有程序统一稳定运行的最终方案。
