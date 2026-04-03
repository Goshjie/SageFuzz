# 3.3.5 测试用例结构化表示与统一执行时间线

3.2.3 节指出，快速重路由等复杂场景的测试需要控制面配置、外部操作和数据面报文在统一时间线上协调执行。本节介绍 P4-BISG 输出的测试用例结构及其核心组件，即统一执行时间线的形式化定义与组装方法。

### （1）测试用例的结构化表示

P4-BISG 的输出不是松散的报文列表，而是具有明确执行语义的结构化测试用例。

**定义 3.7（测试用例）** 测试用例 $\text{TC}$ 定义为四元组

$$\text{TC} = \langle \Pi, E, \Xi, \Omega \rangle$$

各分量含义如下：

- $\Pi = \{\Pi_{\sigma_1}, \Pi_{\sigma_2}, ..., \Pi_{\sigma_n}\}$ 为按场景组织的报文序列集合，每个 $\Pi_{\sigma_i} = \langle p_1, p_2, ..., p_m \rangle$ 为场景 $\sigma_i$ 的有序报文列表，每个报文 $p_j = (\text{tx\_host}, \text{stack}, \text{fields})$ 包含发送主机、协议栈和字段键值。
- $E = \{e_1, e_2, ...\}$ 为控制面实体集合，每个 $e_i = (\text{table}, \text{match}, \text{action}, \text{params})$ 对应一条流表规则。
- $\Xi = \langle \xi_1, \xi_2, ..., \xi_m \rangle$ 为统一执行时间线，是测试用例的执行入口。
- $\Omega = \{\omega_{\sigma_1}, \omega_{\sigma_2}, ...\}$ 为按场景组织的预言机预测集合，每个 $\omega_{\sigma_i}$ 描述该场景的预期行为。

该结构的设计目标不是方便阅读，而是保证生成结果具备明确的执行语义，能够被直接执行。

### （2）统一执行时间线的形式化定义

**定义 3.8（统一执行时间线）** 执行时间线 $\Xi$ 定义为严格有序的操作序列

$$\Xi = \langle \xi_1, \xi_2, ..., \xi_m \rangle, \quad \xi_i.\text{seq} < \xi_{i+1}.\text{seq}$$

每个操作 $\xi_i$ 定义为三元组

$$\xi_i = (\text{seq}_i, \tau_i, \pi_i)$$

其中 $\text{seq}_i \in \mathbb{N}^+$ 为全局序列编号，$\tau_i$ 为操作类型，$\pi_i$ 为操作载荷。操作类型 $\tau$ 属于以下三类之一：

$$\tau \in \{\text{control\_plane\_config}, \text{operator\_action}, \text{send\_packet}\}$$

- $\tau = \text{control\_plane\_config}$：载荷为控制面规则 $e \in E$，表示向目标交换机写入表项。
- $\tau = \text{operator\_action}$：载荷为外部操作描述 $a \in A_{\text{op}}$，表示对网络环境的干预（如断链、通知控制器）。
- $\tau = \text{send\_packet}$：载荷为报文引用 $p \in \Pi$，表示从指定主机发送数据包。

这种设计将异构操作统一编排到同一有序序列中，使回放引擎只需顺序遍历 $\Xi$ 即可完成整个测试执行。

### （3）执行时间线组装算法

算法 3-4 描述了执行时间线的自动组装流程。组装遵循"控制面先于外部动作，外部动作先于数据面报文"的基本顺序原则，并根据场景契约中的步骤结构对数据面报文进行排布。

---

**算法 3-4. 执行时间线组装算法**

**输入：** 控制面实体 $E$，外部操作 $A_{\text{op}}$，报文序列 $\Pi$，场景契约 $\Lambda$

**输出：** 统一执行时间线 $\Xi$

---

1: $\Xi \leftarrow \langle\rangle$, $\text{seq} \leftarrow 1$

2:

3: **// 阶段一：编排控制面配置操作**

4: **for each** $e \in E$ **do**

5: $\quad \Xi.\text{append}((\text{seq}, \text{control\_plane\_config}, e))$

6: $\quad \text{seq} \leftarrow \text{seq} + 1$

7: **end for**

8:

9: **// 阶段二：按场景契约交错编排外部操作与报文发送**

10: **for each** $(\sigma, \mathcal{S}, \Phi) \in \Lambda$ **do**

11: $\quad$ **for each** step $s_j \in \mathcal{S}$ **do**

12: $\quad\quad$ **if** $s_j$ requires preceding operator action $a$ **then**

13: $\quad\quad\quad \Xi.\text{append}((\text{seq}, \text{operator\_action}, a))$

14: $\quad\quad\quad \text{seq} \leftarrow \text{seq} + 1$

15: $\quad\quad$ **end if**

16: $\quad\quad$ **for each** packet $p \in \Pi_\sigma$ mapped to step $s_j$ **do**

17: $\quad\quad\quad \Xi.\text{append}((\text{seq}, \text{send\_packet}, p))$

18: $\quad\quad\quad \text{seq} \leftarrow \text{seq} + 1$

19: $\quad\quad$ **end for**

20: $\quad$ **end for**

21: **end for**

22:

23: **return** $\Xi$

---

### （4）三个场景的执行时间线示例

为直观说明统一执行时间线如何编排不同类型的操作，表 3-6 以三个代表性场景为例，展示其执行时间线的结构。

**表 3-6 三个场景的执行时间线结构示例**

| 序号 | Stateful Firewall | Link Monitor | Fast Reroute |
|:----:|-------------------|--------------|--------------|
| 1 | `config`: 写入基础转发表项 | `config`: 写入探针转发表项 | `config`: 写入主下一跳表项 |
| 2 | `config`: 写入 MAC 重写规则 | `send`: 发送持续业务流量 ×15 | `config`: 写入备份下一跳表项 |
| 3 | `send`: internal 发 SYN | `send`: 发送 probe 报文 | `config`: 写入 MAC 重写规则 |
| 4 | `send`: external 发 SYN-ACK | — | `send`: 发送正常流量（主路径） |
| 5 | `send`: external 主动发 SYN | — | `action`: 断开指定链路 |
| 6 | — | — | `send`: 发送流量（验证备份路径） |
| 7 | — | — | `action`: 通知控制器重收敛 |
| 8 | — | — | `send`: 发送流量（验证新路径） |

该表清晰展示了不同场景中三类操作的交错编排模式。Stateful Firewall 的时间线以"配置→按序发包"为主；Link Monitor 需要先发送大量业务流量驱动计数再发 probe；Fast Reroute 则是三类操作（配置、外部动作、发包）交替出现的最复杂模式。

**图 3-5 三个场景的统一执行时间线对比图**

### （5）产物存储与可追溯记录

为支持实验复现与失败定位，P4-BISG 对每次生成过程保存两类产物：

**场景级 testcase 文件。** 每个场景的完整结构（包含报文序列、规则、执行时间线和预言机预测）序列化为独立的 JSON 文件，便于单场景回放和调试。

**运行级索引文件。** 记录本次运行的总体状态，包含每个场景文件的路径、报文数量、规则数量、各阶段的校验通过/失败信息和生成耗时等统计信息，为批量实验分析提供机器可读的入口。

此外，系统按生成阶段记录每轮的输入与输出轨迹，便于复查审查反馈与结构化对象的变化过程。
