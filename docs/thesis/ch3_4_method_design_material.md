# 3.3 面向网络行为的 P4 意图感知与种子生成技术

前文已经给出了本文研究问题的挑战与定义。本节进一步说明 P4-BISG 的具体实现思路。P4-BISG 以用户给出的完整测试意图为输入，以可执行 testcase 为输出，目标是在不要求用户显式填写底层报文字段、流表键值和观测细节的前提下，自动完成意图理解、角色绑定、时序数据包生成、控制平面规则组织以及预期结果预测。对防火墙程序，系统需要将“内部主机主动发起连接应允许，外部主机主动发起应拒绝”这类行为要求转换为正反两类时序测试场景；对链路监测程序，系统需要将“先驱动业务流量，再读取链路利用率”这类测试目标转换为流量包与 probe 包的组合场景；对快速重路由程序，系统还需要把链路失效这一外部动作纳入测试执行过程。P4-BISG 的方法设计正是围绕这种“面向网络行为构造完整测试场景”的需求展开的。

从整体结构看，P4-BISG 包括程序上下文构建、意图规约、多智能体协同生成和一致性校验四个部分。系统首先对编译产物、控制流图、拓扑和可选源码建立统一程序上下文；随后将用户意图规约为结构化任务；之后通过多智能体协同生成数据包序列、控制平面规则和 oracle；最后通过确定性校验与回退机制输出结构统一、可执行的 testcase 文件。该流程解决的不是单纯“生成若干输入包”的问题，而是从测试意图出发组织可验证的网络行为场景。

**图3-3 P4-BISG 总体技术框架（占位）**

图位说明：此处插入“用户意图输入、程序上下文构建、多智能体协同生成、testcase 输出”四部分组成的总体框图。

## 3.3.1 技术框架与总体流程

P4-BISG 的总体流程可以概括为五个阶段：程序上下文构建、意图采集与测试目标选择、任务规约、场景生成以及结果校验与输出。系统首先读取 P4 程序的编译产物、控制流图和拓扑信息，建立统一程序上下文；随后接收用户完整意图，并要求用户指明当前测试面向数据平面行为还是控制平面规则；之后由多智能体围绕结构化任务依次完成数据包序列生成、规则生成和 oracle 预测；若中间结果不满足约束，则进入修复、重试或回退；最终输出 testcase 文件和 run 级索引文件。

该流程不是一次性的文本生成，而是一个由主控调度器驱动的阶段化生成过程。每一阶段都以上一阶段的结构化结果为输入，并接受独立校验。这样做的直接效果是，意图层的模糊性不会被原样传播到后续阶段，场景生成阶段的错误也不会污染整个工作流。对本系统已经验证的防火墙、重路由和链路监测场景，这种阶段化流程都能够稳定运行。

算法3-1给出了 P4-BISG 的总体工作过程。

**算法3-1 P4-BISG 测试种子生成总体流程**

```text
Input:
    user_intent, test_objective, program_context
Output:
    testcase_set, run_index

1:  initialize program context
2:  collect full user intent and test objective
3:  build multi-agent generation pipeline
4:  repeat
5:      generate task specification from current intent
6:      if clarification is required then
7:          collect additional user answers
8:          update current intent
9:      else
10:         review task specification for semantic completeness
11: until a valid task specification is accepted
12: generate candidate packet sequence
13: review packet sequence against scenario constraints
14: if needed, apply deterministic fallback generation
15: for each scenario do
16:     if rule generation is enabled then
17:         generate and review control-plane rules
18:         if generation fails, apply minimal executable fallback
19:     generate oracle prediction
20:     if oracle is invalid, use fallback oracle
21:     assemble final testcase
22: write testcase set and run index
23: return testcase_set, run_index
```

## 3.3.2 面向网络行为的意图建模与任务规约

P4-BISG 的关键在于将自然语言测试意图规约为后续生成流程可消费的结构化任务。该任务并不是简单的文本摘要，而是一个面向网络行为验证的中间语义契约，用于描述测试目标、角色关系、场景要求、观测对象以及执行中的外部动作。对有状态防火墙，任务规约需要明确 internal 与 external 的角色绑定，并区分正向场景和反向场景；对 Fast Reroute，任务规约需要将“链路断开”“控制器通知”之类的动作显式纳入测试描述；对 Link Monitor，任务规约不仅要表达业务流量驱动，还要表达 probe 查询和结果观测。

从结构上看，任务规约至少包含以下几类信息：待测功能、意图类别、角色绑定、场景契约、外部操作动作、观测要求和生成模式。意图类别用于区分有状态策略、转发行为、链路监测、路径验证和负载分发等不同测试语义；角色绑定将“内部主机”“外部主机”“查询发起方”等抽象角色映射到拓扑中的真实主机；场景契约定义每个场景中应包含哪些步骤以及步骤之间的字段关系；外部操作动作表达链路断开、阈值调整或背景流量施加等非报文行为；观测要求则用于描述应如何判断测试是否成功。

以 Stateful Firewall 为例，用户给出的测试意图通常是“内部主机主动发起连接时允许通信，外部主机主动发起连接时应被拒绝”。系统不会直接据此生成固定模板，而是先规约出：该任务属于有状态策略验证，需要一个正向场景和一个负向场景，需要绑定内部和外部主机角色，需要用时序报文验证方向性策略，并且不应把待测策略本身预先写死到控制平面规则中。随后，数据包生成、规则生成和 oracle 预测均围绕该任务规约展开。正是这一中间层，将用户意图稳定地连接到后续可执行结果。

为降低自然语言歧义带来的传播误差，P4-BISG 在任务规约阶段采用“生成-审查-修订”的闭环方式。系统先根据当前意图生成候选任务规约，再对其进行语义完整性审查；若审查失败，则将反馈回传至意图分析阶段进行修订。只有通过审查的任务规约才进入后续种子生成流程。这样可以避免由于前期任务定义不完整而导致后续阶段生成出语义错误但结构合法的 testcase。

**图3-4 用户意图到任务规约的转换过程（占位）**

图位说明：此处插入“原始意图 -> 角色绑定/场景约束/观测要求 -> 任务规约”的分层转换图，并可使用 firewall 或 link_monitor 作为示例。

算法3-2给出了意图规约与语义审查流程。

**算法3-2 意图规约与语义审查流程**

```text
Input:
    user_intent
Output:
    accepted_task_spec

1:  feedback <- None
2:  for each intent round do
3:      construct structured prompt from current intent and feedback
4:      generate task specification or clarification questions
5:      if clarification questions are returned then
6:          collect user answers
7:          merge answers into current intent
8:          continue
9:      review task specification for semantic completeness
10:     if review passes then
11:         return accepted task specification
12:     feedback <- review result
13: raise failure if no valid task is obtained within retry budget
```

## 3.3.3 多智能体协同的测试种子生成机制

在完成任务规约后，P4-BISG 通过多智能体协同方式生成测试种子。该机制的设计重点不在于引入多个模型本身，而在于将复杂生成任务拆分为边界清晰、便于校验的若干子问题。系统中不同智能体分别承担意图分析、数据包序列生成、约束审查、控制平面规则生成、规则审查和 oracle 预测等职责，主控调度器则负责阶段衔接、重试控制和结果归一化。

这种分工方式对本系统尤为必要。对 Fast Reroute 这类场景，测试不仅包含报文，还包含链路故障和控制器收敛动作；对 Congestion-Aware Load Balancing，系统还需要把“高流量背景干扰”这类外部条件组织到测试场景中。若由单个生成模块同时处理这些异质任务，输出很容易出现语义不完整或结构不一致的问题。多智能体协同机制将“理解任务”“生成报文”“生成规则”“解释预期结果”分开处理，有助于稳定生成质量，并为后续确定性校验提供更清晰的对象边界。

此外，系统还引入了基于意图分桶的记忆机制。其作用不是替代规则生成或约束校验，而是在面对相似测试意图时，为智能体提供可复用的上下文支持。例如，当系统先后处理多个“有状态策略验证”或“链路监测”类任务时，记忆模块可以帮助智能体更快聚焦到相近的任务模式，但最终结果仍须通过确定性校验后才能被接受。

## 3.3.4 测试种子的结构化表示与执行语义

P4-BISG 的输出不是单一数据包集合，而是一个完整的 testcase 结构。该结构至少包含数据包序列、控制平面规则、控制平面操作顺序、统一执行时间线和预期结果描述五类信息。数据包序列描述测试中需要发送的报文及其字段取值；控制平面规则描述测试前需要写入的辅助规则；控制平面操作顺序用于明确规则写入时机；统一执行时间线将控制平面动作、外部动作和报文发送动作组织为单一顺序；预期结果描述则记录逐包的预期接收位置、处理决策以及前后状态变化。

这种结构化输出的意义在于，系统生成的 testcase 不再只是“供人工参考的一组输入”，而是一个具备执行语义的完整测试工件。对 Stateful Firewall，统一执行时间线能够直接表达“先写基础转发规则，再发送正向 SYN，再发送返回 SYN-ACK，再观察是否允许回包”；对 Fast Reroute，统一执行时间线能够表达“先触发链路断开，再发送后续流量，再验证是否走备份路径”；对 Link Monitor，则能够表达“先用业务流量驱动链路计数，再发送 probe，再读取返回结果”。这种组织方式使 testcase 更接近可直接执行的实验脚本，而不是孤立的数据包片段。

算法3-3给出了统一执行时间线的归一化过程。

**算法3-3 测试执行时间线归一化过程**

```text
Input:
    packet_sequence, control_plane_sequence, candidate_execution_sequence
Output:
    normalized_execution_sequence

1:  if candidate execution sequence exists then
2:      reorder and renumber all execution steps
3:      return normalized sequence
4:  separate control-plane actions into pre-traffic and remaining actions
5:  create empty execution sequence
6:  append pre-traffic actions in order
7:  append packet sending actions according to packet sequence order
8:  append remaining actions in order
9:  renumber all steps and return normalized sequence
```

**图3-5 最终 testcase 结构与执行语义示意图（占位）**

图位说明：此处插入“packet_sequence、entities、control_plane_sequence、execution_sequence、oracle_prediction”五部分构成的结构图，并可标注 firewall 或 fast reroute 的场景示例。

## 3.3.5 鲁棒化修复与一致性校验机制

大模型输出在实际运行中不可避免会出现 JSON 不闭合、字段名漂移、类型不匹配、工具参数错误或 schema 解析失败等问题。若不对这些问题进行工程化处理，多智能体工作流很难稳定输出可执行 testcase。为此，P4-BISG 在生成链路中引入了多层鲁棒化修复与一致性校验机制。

第一层是工具参数修复。系统在工具调用前执行 JSON 修复、参数别名归一化、schema 类型纠正和必填字段检查，以降低模型因轻微格式偏差导致工具调用失败的概率。第二层是阶段级重试与回退。若意图规约、数据包生成、规则生成或 oracle 预测阶段无法得到合法结果，系统将触发局部重试；若仍失败，则回退到最小可执行结果生成逻辑，以保证整体流程不中断。第三层是确定性校验。无论结果来自模型生成还是回退生成，都必须通过结构、约束和一致性检查，包括场景是否缺失、协议栈是否匹配、字段是否满足契约、角色绑定是否一致以及 oracle 是否与报文序列一一对应。只有通过这些校验的结果，才会写入最终 testcase。

这种“模型生成-工程修复-确定性校验-回退输出”的组合机制，是 P4-BISG 能够在多个程序上稳定运行的基础。它表明，系统的稳定性并不单纯依赖模型本身，而是依赖于方法设计与工程控制的共同作用。

## 3.3.6 本节小结

本节给出了 P4-BISG 的具体技术方案。该方法以用户测试意图为中心，通过程序上下文构建、任务规约、多智能体协同生成、结构化 testcase 表达以及多层鲁棒化修复与一致性校验机制，完成了从自然语言测试意图到可执行测试种子的自动转换。与主要面向路径覆盖或种子扩张的既有方法不同，P4-BISG 的方法重点在于围绕网络行为语义组织完整测试场景，而不是仅生成若干输入报文。后续实验将围绕生成开销、状态覆盖、缺陷触发和直接回放能力对该方法进行验证。
