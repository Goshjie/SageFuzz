# 3.4 面向网络行为的 P4 意图感知与种子生成方法设计

在前述问题定义与设计目标的基础上，本节给出 P4-BISG 的方法设计。P4-BISG 的目标不是为某一类 P4 程序定制固定模板，而是建立一条面向网络行为测试的统一生成路径，使系统能够将用户提出的高层测试意图逐步转换为可执行 testcase。围绕这一目标，本文从系统总体架构、程序上下文建模、任务规约、多智能体协同生成、testcase 结构化表示以及一致性约束与鲁棒化机制六个方面展开说明。

## 3.4.1 系统总体架构与模块交互

从系统组织形式看，P4-BISG 采用分层架构。整体上可划分为输入层、程序上下文层、生成与调度层以及结果输出层四个部分。输入层负责接收用户测试意图、测试目标类型以及运行配置；程序上下文层负责将编译产物、控制流结构、拓扑信息和可选源码整理为统一上下文；生成与调度层负责将测试意图规约为结构化任务，并进一步驱动数据包、规则和 oracle 的生成；结果输出层负责完成一致性校验、失败回退和 testcase 落盘。图3-3给出了这一架构及其模块间交互关系。

其中，程序上下文层是整套方法的约束基础。该层并不只是简单加载若干输入文件，而是将解析器路径、控制流关系、表项结构、状态对象和拓扑信息组织为可共享的结构化证据集合。后续各生成模块均不直接依赖原始文件，而是通过这一统一上下文获取约束依据。这样做的结果是，意图规约、数据包生成、规则组织和 oracle 预测都建立在同一份程序语义基础之上，减少了不同阶段对程序理解不一致的问题。

生成与调度层由工作流调度模块和多智能体协同模块共同构成。工作流调度模块位于生成链路的中枢位置，负责管理阶段顺序、记录中间结果以及控制重试与回退；多智能体协同模块则负责具体生成任务，包括意图分析、任务审查、数据包生成、规则生成、规则审查和 oracle 预测。两者之间并不是替代关系，而是“调度控制”和“内容生成”的分工关系：前者决定何时调用、调用谁以及失败后如何处理，后者负责在当前阶段给出结构化结果。

从信息流动方式看，P4-BISG 的模块交互可以概括为两条主线和一条反馈链。第一条主线是任务规约链，即用户意图经过语义分析和审查后形成结构化任务；第二条主线是测试种子生成链，即任务规约进一步驱动数据包序列、控制平面规则和 oracle 的生成；反馈链则由审查、校验和回退构成，贯穿于主流程之中。当某一阶段结果不满足约束时，系统不会整体推翻已有流程，而是将问题局限在当前阶段，通过局部反馈、阶段重试或最小可执行回退维持整体可用性。这种设计使系统具有较好的稳定性，也使生成过程更容易定位问题来源。

从方法目标看，这一架构解决的不是单纯“调用多个智能体生成文本”的问题，而是如何在不同语义层之间建立稳定映射。输入层提供用户意图，程序上下文层提供程序证据，生成与调度层完成从高层语义到结构化 testcase 的转换，结果输出层则保证输出具备执行价值。由于四层之间通过结构化对象而非自由文本连接，系统能够在保持语义完整性的同时控制生成复杂度，并为后续实验中的状态覆盖、缺陷触发和直接回放提供统一输入形式。

**图3-3 P4-BISG 系统总体架构与模块交互关系（占位）**

图位说明：此处插入系统总体架构图，图中至少应体现输入层、程序上下文层、生成与调度层和结果输出层四个层次，以及任务规约链、种子生成链和反馈链三类交互关系。

在上述总体架构基础上，下面依次说明程序上下文如何提供约束基础、任务规约如何将测试意图转换为中间语义对象、多智能体如何完成协同生成，以及最终 testcase 如何被组织为具备执行语义的结构化结果。

算法3-1给出了 P4-BISG 在系统层面的总体调度过程。

**Algorithm 3-1 P4-BISG Orchestration Algorithm**

```text
Input:
    user_intent, test_objective, program_context
Output:
    testcase_set

1:  collect complete user intent
2:  construct program context
3:  generate and review task specification
4:  generate and review packet sequence
5:  if rule generation is enabled then
6:      generate and review control-plane rules
7:  generate oracle prediction
8:  validate, repair, or fallback when needed
9:  assemble testcase and write outputs
10: return testcase_set
```

## 3.4.2 程序上下文建模

P4-BISG 的第一步不是直接生成测试数据，而是建立统一的程序上下文。其原因在于，测试意图虽然来自用户，但最终能否生成有效 testcase 取决于目标程序的真实结构。若缺少编译产物、控制流关系和拓扑约束，系统即便能够生成语义上合理的描述，也难以进一步落实为可执行结果。

在本文方法中，程序上下文由三类信息构成。第一类是程序结构信息，用于描述解析器支持哪些协议路径、控制流中有哪些关键表项和动作、程序是否包含寄存器、计数器等状态对象。第二类是拓扑与主机信息，用于确定测试中的真实发送者、接收者以及角色与主机之间的绑定关系。第三类是可选源码信息，用于在需要时补充程序语义证据，帮助系统理解某些监测字段、状态更新逻辑或动作含义。

上述上下文并不是作为长文本直接输入给大语言模型，而是以可查询的结构化形式被组织起来。在生成过程中，系统只在需要时按需检索局部证据，如解析器路径、表项签名、状态对象或拓扑主机信息。这样做的目的有两点：其一，减少不必要的上下文冗余，避免模型在大段静态文本中丢失关键约束；其二，将程序理解过程建立在明确证据之上，使后续生成结果更易于校验和解释。

从方法上看，程序上下文建模为后续所有阶段提供了共同基础。任务规约必须参考拓扑与程序结构，数据包生成必须参考解析器与字段约束，规则生成必须参考表项与动作签名，oracle 预测也必须参考程序行为边界。若没有统一程序上下文，这些阶段只能依赖模型的先验猜测，难以保证生成质量。

## 3.4.3 意图驱动的任务规约机制

P4-BISG 的第二步是将自然语言测试意图规约为结构化任务。该过程并不是简单抽取关键词，而是围绕“待测行为、角色关系、场景边界、外部动作和观测要求”构造中间语义对象，使后续生成过程具有明确约束。

在本文方法中，任务规约至少回答以下几个问题：测试目标属于哪一类网络行为；测试中涉及哪些逻辑角色，这些角色应映射到哪些真实主机；测试场景由几个子场景构成，各子场景之间是否需要正反例配对；执行过程中是否需要引入链路失效、阈值调整、控制器通知或背景流量等外部动作；结果应通过何种方式进行观察和判定。经过这一过程，原始意图由自然语言描述转化为结构化任务规约，为后续种子生成提供统一约束。

任务规约并非一次生成后直接采用，而是经过语义审查后才能进入下一阶段。审查的重点不是语法完整性，而是规约是否遗漏关键场景、是否忽略必要角色、是否缺少外部动作或观测条件。如果规约未通过审查，系统将根据反馈重新修订任务描述，直到形成可接受的结构化任务。这种“规约-审查-修订”机制使任务阶段具备自我纠偏能力，避免早期意图理解偏差直接扩散到后续种子生成。

算法3-2给出了意图驱动任务规约的主要过程。

**Algorithm 3-2 Intent-Driven Task Specification Algorithm**

```text
Input:
    user_intent, program_context
Output:
    task_spec

1:  initialize current intent description
2:  repeat
3:      infer intent category and test objective
4:      bind logical roles to topology hosts
5:      construct scenario-level constraints
6:      infer external actions and observation requirements
7:      assemble structured task specification
8:      review semantic completeness of the task
9:  until the task passes review or retry budget is exhausted
10: return accepted task specification
```

**图3-4 用户意图到任务规约的转换过程（占位）**

图位说明：此处插入“原始意图 -> 角色绑定 -> 场景约束 -> 外部动作/观测要求 -> 结构化任务”的转换图。

## 3.4.4 多智能体协同生成机制

在得到结构化任务后，P4-BISG 采用多智能体协同方式完成测试种子的生成。采用该设计的原因在于，完整 testcase 的生成包含多类性质不同的子问题：意图理解、数据包构造、规则组织、结果解释和一致性审查。这些任务若由单一生成模块统一处理，容易在一个阶段中同时混入协议约束、拓扑约束、控制平面约束和语义解释，导致输出结构不稳定，也不利于后续校验。

因此，本文将生成过程划分为若干职责明确的子模块。语义分析模块负责将用户意图规约为结构化任务；数据包生成模块根据任务生成候选报文序列；约束审查模块负责检查任务规约和报文序列是否满足场景约束；规则生成模块负责在需要时组织控制平面规则；规则审查模块负责检查生成的规则是否符合表结构约束；oracle 预测模块则根据场景和执行条件，为每个报文给出预期结果描述。主控调度器位于各模块之上，负责阶段衔接、结果收集、失败回退和统一输出。

这种协同机制的重点不在于增加生成步骤数量，而在于提高每一步的边界清晰度。数据包生成模块只关注如何给出满足任务约束的输入，规则生成模块只关注如何形成可执行的控制条件，oracle 模块只关注如何描述预期结果。各模块之间通过结构化对象传递信息，从而降低不同语义层交叉干扰的概率。对本研究关注的网络行为测试任务而言，这种分工方式更容易形成完整、可校验的测试场景。

此外，系统支持基于意图相似性的记忆复用。其作用是为相似任务提供辅助上下文，而非替代规则约束与一致性校验。也就是说，记忆机制只能帮助系统更快聚焦于相近任务模式，最终输出仍需经过结构和语义双重校验后才能被接受。

为了更直观地说明多智能体如何协同生成最终 testcase，算法3-4给出了 testcase 的生成过程。该过程强调的不是单个智能体如何产生文本输出，而是主控调度器如何将任务规约、数据包序列、控制平面规则、执行顺序与 oracle 逐步整合为统一测试工件。

**Algorithm 3-4 Testcase Generation Algorithm**

```text
Input:
    accepted task_spec, program_context
Output:
    testcase_set

1:  initialize empty testcase set
2:  for each scenario in task_spec do
3:      generate packet-sequence candidate for the scenario
4:      review packet-sequence candidate against scenario constraints
5:      if packet sequence is invalid then
6:          repair, retry, or use packet fallback
7:      if generation mode requires rules then
8:          generate control-plane rule candidate
9:          review rule candidate against table and action constraints
10:         if rule set is invalid then
11:             repair, retry, or use rule fallback
12:     else
13:         skip rule generation and keep packet-only execution path
14:     derive unified execution sequence from packets, rules, and operator actions
15:     generate oracle prediction for the scenario
16:     if oracle is invalid then
17:         use oracle fallback
18:     assemble testcase from packet sequence, rules, execution sequence, and oracle
19:     append testcase to testcase set
20: return testcase set
```

## 3.4.5 测试种子的结构化表示

P4-BISG 输出的不是单一报文文件，而是一个具备执行语义的 testcase。其结构至少包含五类信息：数据包序列、控制平面规则、控制平面操作序列、统一执行时间线和预期结果描述。

数据包序列描述测试中需要发送的各个报文及其头字段；控制平面规则用于表达测试前应具备的基础可达条件或辅助规则；控制平面操作序列用于给出规则写入顺序；统一执行时间线用于将控制平面动作、外部动作和报文发送动作组织为单一顺序；预期结果描述用于记录逐包的预期接收位置、处理决策以及前后状态变化。通过这种结构化表达，系统输出的 testcase 不再只是“若干输入”，而是一个包含执行顺序和预期语义的完整测试工件。

这一设计的意义在于，后续实验不必再根据生成结果人工组织执行步骤。对于涉及链路断开、阈值调整或背景流量驱动的场景，执行时间线可以直接表达“何时执行动作、何时发包、何时观察”；对于状态型程序，预期结果描述可以直接给出每一步应到达的状态和接收端。因此，testcase 结构化表示既服务于生成阶段，也服务于后续实验回放和结果比对。

算法3-5给出了测试执行时间线的构造过程。

**Algorithm 3-5 Execution Sequence Construction Algorithm**

```text
Input:
    packet_sequence, control_actions, operator_actions
Output:
    execution_sequence

1:  initialize empty execution sequence
2:  append pre-traffic control actions
3:  append required operator actions at their specified timing
4:  append packet sending actions in packet order
5:  append remaining control actions if needed
6:  renumber all actions to form a single executable timeline
7:  return execution sequence
```

**图3-5 最终 testcase 结构示意图（占位）**

图位说明：此处插入 testcase 的组成结构图，包括 `packet_sequence`、`entities`、`control_plane_sequence`、`execution_sequence` 和 `oracle_prediction`。

## 3.4.6 一致性约束与鲁棒化机制

P4-BISG 依赖大语言模型完成意图理解和种子生成，因此必须处理模型输出中的结构不稳定问题。若缺乏必要约束，模型可能生成格式不闭合的结果、字段名与真实头部不一致的报文，或者与程序表结构不匹配的控制规则。为此，本文在方法中引入了一致性约束与鲁棒化机制，使生成过程在面对不稳定输出时仍能保持可用。

其一，系统在工具调用前执行参数修复，包括 JSON 修复、参数名归一化、类型纠正和必填项补齐，以降低轻微格式误差对后续生成造成的影响。其二，系统在各生成阶段设置重试和回退逻辑。若某一阶段无法输出合法结果，则优先进行局部重试；若重试后仍失败，则退回最小可执行生成逻辑，以保证整体流程不中断。其三，系统对各阶段结果执行确定性校验，包括场景是否缺失、协议栈是否匹配、字段是否满足约束、角色绑定是否一致以及 oracle 是否与报文序列一一对应。只有通过这些校验的结果，才被写入最终 testcase。

这种设计意味着，P4-BISG 的稳定性并不单纯依赖模型一次性输出正确结果，而是建立在“生成-修复-校验-回退”这一闭环之上。对工程系统而言，这种方法更符合实际需求，因为它能够在模型存在不可避免误差的情况下，仍维持整体 testcase 生成能力。

## 3.4.7 本节小结

本节从方法层面对 P4-BISG 的设计进行了说明。该方法以程序上下文为约束基础，以用户意图为生成起点，通过任务规约、多智能体协同生成、结构化 testcase 表达以及一致性约束与鲁棒化机制，完成了从自然语言测试目标到可执行测试种子的自动转换。其关键特征不在于单纯生成更多输入，而在于围绕网络行为语义组织完整测试场景。后续实验将进一步验证该方法在生成开销、状态覆盖、缺陷触发和直接回放方面的效果。
