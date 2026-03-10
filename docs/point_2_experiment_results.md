# 第二创新点实验结果记录

## 1. 实验目标

本轮实验用于回答两个问题：

1. 为什么第二创新点优先选择 `Agent5` 作为小模型下沉对象；
2. 为什么不能简单地把所有 agent 统一切换为小模型。

## 2. 说明：早期实验与可联网重跑

本轮排查过程中，曾出现一批受到沙箱网络限制影响的早期实验记录。这些实验的典型表现是：

- `Connection error`
- DNS 解析失败
- provider 无法稳定连通

后续已通过脱离沙箱环境验证：底层 `curl` 与 `requests` 可直接访问 DashScope 接口，`Agno + qwen3-4b` 的最小 JSON 输出也能稳定返回。因此，本文件后续结论以**可联网环境下重跑后的实验结果**为准；早期受网络限制影响的记录只保留为排障背景，不作为最终论据。

## 3. 实验一：全流程自动化尝试

已执行三任务 × 三配置的自动化全流程实验，实验脚本为：

- `scripts/run_point2_experiments.py:1`

输出目录：

- `runs/point2_experiments_2026-03-09T132844Z`
- `runs/point2_experiments_2026-03-09T133903Z`
- `runs/point2_experiments_2026-03-09T134748Z`

### 2.1 实验设置

任务：

- `firewall`
- `link_monitor`
- `fast_reroute`

配置：

- `baseline`
- `agent5_small`
- `all_small`

### 2.2 结果

当前租用环境下，直接用 DashScope/Qwen 模型替换真实全流程 agent 时，实验未能稳定进入完整 testcase 生成阶段，日志中出现两类问题：

1. `Agent1` 在真实 tool-heavy 提示词与上下文下出现连接错误或多轮失败；
2. 非交互批处理时，若 `Agent1` 继续追问，会导致全流程无法继续推进。

其中第二类问题已通过工作流非交互安全处理修复；第一类问题在当前 provider + 当前完整工具栈组合下仍然存在。

这说明：

- **当前小模型/当前 provider 组合并不适合直接对整条多智能体链路做端到端统一替换**；
- 至少在现阶段，不能简单把“全小模型”当作默认可行方案。

## 4. 实验二：真实输入下的 agent 级回放

为避免全流程 provider 不稳定掩盖 agent 角色本身的差异，本轮进一步采用历史真实输入做 agent 级回放。

### 3.1 小模型下的真实 agent 回放

脚本：

- `scripts/replay_point2_single_sample.py:1`
- `scripts/replay_point2_agent_samples.py:1`

输出目录：

- `runs/point2_agent_replays_2026-03-09T142328Z`

回放任务：

- `firewall`
- `link_monitor`
- `fast_reroute`

回放节点：

- `agent1`
- `agent2`
- `agent4`
- `agent5`

### 3.2 结果

回放结果如下：

- `firewall / agent1`：`timeout`
- 其余样本：大多返回 `invalid_output`
- 主要无效形式为：`"Connection error."`

结果表见：

- `runs/point2_agent_replays_2026-03-09T142328Z/summary.md`

这说明：

- 当保留真实 agent 构造方式（含完整 prompt、工具集、schema 调用）时，**小模型在当前环境下并不能稳定承担所有 agent 的职责**；
- 尤其是上游生成型节点和依赖完整工具栈的节点，统一切小模型并不可取。

因此，“全小模型”并不是一个稳妥方案。

## 5. 实验三：Agent5 prompt-only 回放

考虑到第二创新点本身要证明的是“结构化审查型节点适合下沉”，因此进一步将 `Agent5` 从完整 tool stack 中剥离，只保留：

- 真实 `Agent5` prompt
- 真实历史输入样本
- 小模型直接输出 `CriticResult`

脚本：

- `scripts/replay_point2_agent5_prompt_only.py:1`

输出目录：

- `runs/point2_agent5_prompt_only_2026-03-09T143037Z`

### 4.1 结果

三个任务全部成功返回合法 `CriticResult`：

- `firewall`：`PASS`
- `link_monitor`：`PASS`
- `fast_reroute`：`FAIL`

结果表见：

- `runs/point2_agent5_prompt_only_2026-03-09T143037Z/summary.md`

### 4.2 结果解释

该结果至少说明了以下事实：

1. 小模型能够在真实 `Agent5` 提示词与真实输入上稳定输出合法结构化结果；
2. 小模型不是简单“全 PASS”或“全 FAIL”，而是能够做出区分；
3. 对于 `firewall` 与 `link_monitor`，小模型给出的审查结论可直接作为正向证据；
4. 对于 `fast_reroute`，小模型倾向于给出更保守的 `FAIL`，说明它在更复杂控制面时序场景下仍存在收紧倾向。

## 6. 补充实验：qwen2.5-7b-instruct

在 `qwen3-4b` 之外，本轮进一步补做了 `qwen2.5-7b-instruct` 的全流程实验、真实节点回放和 `Agent5` prompt-only 回放，用于比较不同小模型在当前环境下的稳定性差异。

### 6.1 全流程结果

脚本：

- `scripts/run_point2_experiments.py:1`

输出目录：

- `runs/point2_experiments_2026-03-10T045533Z`

摘要结果如下：

- `firewall / baseline`：成功，wall-clock 时间约 `395.95 s`
- `firewall / agent5_small`：失败，wall-clock 时间约 `16.26 s`
- `firewall / all_small`：失败，wall-clock 时间约 `16.34 s`
- `link_monitor` 三组：均失败，wall-clock 时间约 `16.12 s` 到 `16.81 s`
- `fast_reroute` 三组：均失败，wall-clock 时间约 `15.75 s` 到 `16.35 s`

可以看出，`qwen2.5-7b-instruct` 在全流程上并未稳定优于前一轮的更小模型方案。除基线外，其余组在多数任务上很快失败，说明当前 provider 与真实多 agent 链路的耦合问题仍然存在。

### 6.2 真实节点回放结果

脚本：

- `scripts/replay_point2_agent_samples.py:1`

输出目录：

- `runs/point2_agent_replays_2026-03-10T050647Z`

该轮回放增加了 wall-clock 时间记录。结果显示：

- `firewall / agent1`：`invalid_output`，但耗时达到 `37.94 s`
- `firewall / agent2`：`success`，耗时 `125.54 s`
- 其余多数样本：`invalid_output`，耗时通常低于 `1 s`

这说明 `qwen2.5-7b-instruct` 在少数单节点任务上可以给出合法结构化输出，但一旦进入更复杂的真实 agent 构造路径，仍然会频繁出现无效结果。与 `qwen3-4b` 相比，它在 `Agent2` 上展现出更强的局部可用性，但还不足以直接支撑整条链路的系统级替换。

### 6.3 Agent5 prompt-only 结果

脚本：

- `scripts/replay_point2_agent5_prompt_only.py:1`

输出目录：

- `runs/point2_agent5_prompt_only_2026-03-10T050648Z`

三项任务全部成功，且记录了 wall-clock 时间：

- `firewall`：`PASS`，`4.35 s`
- `link_monitor`：`PASS`，`5.19 s`
- `fast_reroute`：`FAIL`，`5.35 s`

与早先的 `runs/point2_agent5_prompt_only_2026-03-09T143037Z` 一致，这一结果再次说明：`Agent5` 在 prompt-only 条件下确实适合小模型下沉，`qwen2.5-7b-instruct` 也能稳定承担该角色。

## 7. 补充实验：qwen3-4b 的可联网重跑

在确认底层网络与 API 可达之后，又对 `qwen3-4b` 做了可联网环境下的重跑，重点包括：

- `Agent5` prompt-only 回放：`runs/point2_agent5_prompt_only_2026-03-10T061210Z`
- 真实 agent 回放：`runs/point2_agent_replays_2026-03-10T061209Z`
- `firewall` 重复实验：`runs/point2_firewall_repeats_2026-03-10T065438Z`

### 7.1 qwen3-4b 的 Agent5 prompt-only 结果

可联网环境下，`qwen3-4b` 的 `Agent5` prompt-only 三项任务全部成功：

- `firewall`：`PASS`，`3.02 s`
- `link_monitor`：`PASS`，`2.99 s`
- `fast_reroute`：`PASS`，`2.48 s`

这说明先前 `qwen3-4b` 在 prompt-only 场景中的失败并不是模型本身一定不能执行该角色，而是早期受连接层限制影响较大。

### 7.2 qwen3-4b 的真实 agent 回放结果

真实 agent 回放结果表明，`qwen3-4b` 在当前环境下已经具备明显优于早期记录的局部可用性：

- `Agent2` 在三个任务上均能成功回放；
- `Agent5` 在 `firewall` 与 `link_monitor` 上成功，在 `fast_reroute` 上仍未稳定；
- `Agent1` 和 `Agent4` 仍然普遍表现为 `invalid_output`。

这说明 `qwen3-4b` 并非“整体不可用”，而是更适合承担边界清晰的局部节点任务；对上游开放式规约节点与复杂控制面生成节点，当前仍缺乏稳定性。

### 7.3 qwen3-4b 的 firewall 重复实验

为验证 `firewall` 场景下的波动是否偶然，本轮在可联网环境下又做了 2 轮重复实验：

- 输出目录：`runs/point2_firewall_repeats_2026-03-10T065438Z`

统计结果如下：

- `baseline`：2 轮中 1 轮 `PASS`，1 轮失败；
- `agent5_small`：2 轮全部失败；
- `all_small`：2 轮全部失败。

这说明，在排除网络限制后，`qwen3-4b / firewall / all_small` 仍然没有形成稳定可复现的正结果。此前出现的个别单次成功并不足以支撑“全小模型方案成立”的结论。

## 8. 补充实验：firewall 重复对照

为排除单次运行偶然性，本轮又对 `firewall` 任务在 `qwen3-4b` 条件下做了 3 轮重复实验。

脚本：

- `scripts/repeat_point2_firewall_modes.py:1`

输出目录：

- `runs/point2_firewall_repeats_2026-03-10T052138Z`

统计结果如下：

- `baseline`：3 轮中 2 轮成功运行；其中 `PASS` 1 次、`FAIL` 1 次，平均 wall-clock 时间约 `133.74 s`
- `agent5_small`：3 轮中 2 轮运行完成；两次均为 `FAIL`，平均 wall-clock 时间约 `186.90 s`
- `all_small`：3 轮中 1 轮运行完成；该次结果为 `FAIL`，平均 wall-clock 时间约 `51.30 s`

这个重复实验说明，先前 `qwen3-4b / firewall / all_small` 的单次 `PASS` 并不稳定。重复运行后，该配置并没有持续复现正结果，反而大多数轮次失败。因此，不能把单次成功解读为“全小模型方案已经成立”，更合理的结论是：该结果具有明显波动性，现阶段不足以支持统一下沉。

## 9. 当前结论

基于本轮实验，可以得到以下阶段性结论：

### 5.1 为什么选 Agent5

`Agent5` 之所以适合作为第二创新点的首个小模型下沉节点，是因为：

- 它的任务是结构化审查，而不是开放式生成；
- 输入输出边界清晰；
- 在真实 prompt-only 回放中，小模型能够稳定给出合法 `CriticResult`；
- 即使判断偏差，系统后续仍有 deterministic validator 兜底。

### 5.2 为什么不是全部切成小模型

从本轮真实 agent 回放与全流程尝试来看：

- 当前小模型在完整 tool-heavy agent 栈中并不能稳定承担所有节点职责；
- 上游生成型节点和复杂工具调用节点统一切小模型，会导致超时、连接错误或无效输出；
- 因此，“角色感知的异构模型分工”是比“全小模型统一替换”更稳妥、更合理的方案。

## 10. 下一步建议

下一阶段建议围绕以下方向继续推进：

1. 保持大模型负责 `Agent1`、`Agent2`、`Agent4` 等开放式生成节点；
2. 将 `Agent5` 作为主实验对象，继续做系统级替换实验；
3. 若后续需要进一步增强结论，可考虑：
   - 为 `Agent5` 去除不必要工具依赖；
   - 基于历史 `Agent5` 输入输出构建微调数据；
   - 再评估 `Agent5` 小模型在完整 workflow 中的稳定性。
