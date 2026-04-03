# 3.3.2 规范语义规约与任务分解

P4LTL 时序规范以声明式方式描述了待验证的跨包时序性质，但可执行测试种子需要精确的场景结构、角色绑定、时序步骤和观测标准。为解决二者之间的结构性映射差距，P4-BISG 引入结构化任务规约对象 TaskSpec 作为规范与执行之间的桥梁。本节首先给出规范语义规约问题的形式化定义，然后说明 P4LTL 规范的结构化分解方法，最后给出规约算法。

### （1）规范语义规约问题的形式化定义

**定义 3.1（P4LTL 规范语义规约映射）** 给定 P4LTL 时序规范 $S = \langle \mathcal{P}, \mathcal{F}_{\text{fair}}, \mathcal{V}, \mathcal{C}_{\text{cpi}} \rangle$ 与程序上下文 $C = \langle P_{\text{bmv2}}, G_{\text{cfg}}, T_{\text{topo}}, \Sigma_{\text{src}} \rangle$，规范语义规约的目标是求解映射函数

$$f_{\text{spec}}: S \times C \rightarrow Q$$

其中 P4LTL 规范的各分量含义如下：

- $\mathcal{P} = \{\psi_1, \psi_2, ..., \psi_n\}$ 为 `#LTLProperty` 性质集合，每条 $\psi_i$ 是由时序算子（`[]`、`<>`、`X`、`U`、`W`）与原子命题 $\text{AP}(\cdot)$ 组合而成的时序逻辑公式。
- $\mathcal{F}_{\text{fair}}$ 为 `#LTLFairness` 公平性约束，限定关注的输入包类型或到达模式。
- $\mathcal{V} = \{v_1: \tau_1, ..., v_k: \tau_k\}$ 为 `#LTLVariables` 自由变量声明，用于量化特定流实例或寄存器索引。
- $\mathcal{C}_{\text{cpi}}$ 为可选的 `#CPI_SPEC` 控制面约束，指定表匹配与动作调用的假设。

输出 $Q$ 为结构化任务规约对象，定义为六元组

$$Q = \langle \kappa, R, A_{\text{op}}, O_{\text{obs}}, \Lambda, \mu \rangle$$

各分量的含义如下：

- $\kappa \in \mathcal{K}$ 为意图类别，$\mathcal{K} = \{\text{stateful\_policy}, \text{monitoring}, \text{path\_verification}, \text{load\_distribution}, ...\}$ 为预定义的有限类别集合，用于选择后续的生成策略。
- $R = \{(r_i, h_i)\}_{i=1}^{|R|}$ 为角色绑定集合，将 P4LTL 原子命题中隐含的逻辑角色 $r_i$（如 internal、external、probe\_sender）映射到拓扑中的真实主机 $h_i \in T_{\text{topo}}.\mathcal{H}$。
- $A_{\text{op}} = \{a_1, a_2, ...\}$ 为外部操作动作集合，包括 P4LTL 规范隐含的环境操作前提（如改变 `linkState` 寄存器以模拟链路故障）。
- $O_{\text{obs}} = \{o_1, o_2, ...\}$ 为观测需求集合，从 P4LTL 谓词（如 `drop`、`fwd(port)`、寄存器条件）中提取观测目标及判定方法。
- $\Lambda = \{(\sigma_i, \mathcal{S}_i, \Phi_i)\}_{i=1}^{n}$ 为场景契约集合，其中 $\sigma_i$ 为场景标识，$\mathcal{S}_i = \langle s_1, s_2, ..., s_{m_i} \rangle$ 为该场景的有序逻辑步骤序列，$\Phi_i$ 为跨步骤字段关系约束。
- $\mu \in \{\text{packet\_only}, \text{packet\_and\_entities}\}$ 为生成模式标识，由 `#CPI_SPEC` 的存在与否以及表项依赖分析决定。

**定义 3.2（规约的约束条件）** 映射 $f_{\text{spec}}$ 输出的 $Q$ 必须满足以下三类约束：

**(a) 角色约束：** 每个逻辑角色必须绑定到拓扑中存在的真实主机。

$$\forall (r, h) \in R: \quad h \in T_{\text{topo}}.\mathcal{H}$$

**(b) 时序约束：** 每个场景内的逻辑步骤序列满足严格偏序关系，且步骤间的先后关系与 P4LTL 时序算子的语义一致。

$$\forall (\sigma, \mathcal{S}, \Phi) \in \Lambda, \forall j \in [1, |\mathcal{S}|-1]: \quad \mathcal{S}[j] \prec \mathcal{S}[j+1]$$

**(c) 可观测约束：** 每个观测目标引用的对象必须存在于目标程序的字段空间或有状态对象集合中。

$$\forall o \in O_{\text{obs}}: \quad o.\text{target} \in P_{\text{bmv2}}.\mathcal{F} \cup P_{\text{bmv2}}.\mathcal{S}_{\text{obj}}$$

### （2）P4LTL 规范的结构化分解方法

P4LTL 规范的分解过程需要将声明式的时序逻辑转化为操作性的测试结构。本文将分解过程划分为三个维度，对应原论文 3.3.2 中的三步递进式拆解。

**维度一：时序逻辑分离——从时序算子到场景结构。** P4LTL 中的 `always-implies`（`[] (AP(...) ==> ...)`）模式是最常见的性质结构。当一个规范包含多条 `#LTLProperty`，且前件条件互斥或描述不同状态区域时，每条性质自然对应一个独立的测试场景。例如，有状态防火墙的两条性质分别对应内部发起放行和外部发起丢弃两个场景。

时序算子 `X`（next）被映射为场景内的步骤顺序依赖：当前步骤的包处理必须先于下一步骤发生。`<>`（eventually）被映射为最终需要观测到某个结果的观测需求。`U`（until）和 `W`（weak-until）被映射为某条件持续保持直到另一条件成立的多步骤持续约束，在测试中通常表现为重复发包驱动计数累积的行为。

**维度二：控制面约束提取——从 CPI\_SPEC 到规则需求。** 若规范包含 `#CPI_SPEC`，则其中引用的 `Apply(table, action)` 谓词直接指定了控制面需要预配置的表项与动作。即使不存在显式的 `#CPI_SPEC`，当原子命题中引用了 `hit(t)` 或 `key(t, k)` 等流表相关谓词时，也隐含了对应表项必须被配置的控制面前提。系统通过查询 BMv2 JSON 中的表签名获取匹配键与动作参数的具体结构。

**维度三：数据面特征映射——从原子命题到报文约束。** P4LTL 原子命题 `AP(...)` 内部的谓词表达式直接对应测试报文应满足的字段约束。具体映射规则如下：

- `valid(hdr.X)`：报文必须包含协议头 X，对应协议栈约束。
- `hdr.X.field comp value`：字段 `field` 的取值约束，对应步骤级的字段期待。
- `drop` / `!drop`：转化为观测需求中的丢弃/放行判定。
- `fwd(port)`：转化为观测需求中的转发端口判定。
- `old(...)` 引用：标识了报文处理前的初始值，可辅助推导发送时的字段设置。
- `meta.X` / `register[idx]`：元数据和寄存器引用，需要通过程序上下文查询确认其语义与位宽。

公平性条件 `#LTLFairness` 则被映射为测试环境的前提约束，指定了在什么类型的流量持续到达的条件下性质应成立，对应测试中需要注入的背景流量模式或包类型过滤条件。

### （3）场景契约的结构化表示

场景契约 $\Lambda$ 是 TaskSpec 的核心组件，负责将 P4LTL 规范中隐含的行为结构显式化为可校验的场景-步骤层次。

每个场景 $\sigma_i$ 的步骤序列 $\mathcal{S}_i$ 中的逻辑步骤 $s_j$ 定义为

$$s_j = (\text{desc}_j, \text{role}_j, \text{proto}_j, n_j)$$

其中 $\text{desc}_j$ 为从 P4LTL 原子命题中提取的步骤行为描述，$\text{role}_j \in R$ 为该步骤的发送角色，$\text{proto}_j$ 为从 `valid(hdr.X)` 谓词推导的协议栈类型，$n_j \in \mathbb{N}^+$ 为重复次数（由 `eventually` 或 `until` 类算子推导，用于表示持续流量驱动或多次探测）。

跨步骤字段关系 $\Phi_i$ 定义为一组约束谓词

$$\Phi_i = \{\phi_{jk} \mid j, k \in [1, |\mathcal{S}_i|], j \neq k\}$$

其中 $\phi_{jk}$ 描述步骤 $j$ 与步骤 $k$ 之间的字段依赖关系。例如，在有状态防火墙场景中，P4LTL 中 `X` 算子连接的前后两个原子命题隐含了 SYN-ACK 回包（步骤 2）的源/目的 IP 应与 SYN 包（步骤 1）的目的/源 IP 互换，可形式化为

$$\phi_{12}: s_2.\text{src\_ip} = s_1.\text{dst\_ip} \wedge s_2.\text{dst\_ip} = s_1.\text{src\_ip}$$

### （4）基于程序上下文的 P4LTL 规范规约算法

算法 3-1 给出了 P4-BISG 中 P4LTL 规范语义规约的具体流程。该算法以 P4LTL 规范和程序上下文为输入，通过时序逻辑分离、角色绑定、场景构造和契约审查四个阶段，逐步将声明式时序规范转化为满足约束条件的 TaskSpec 对象。

---

**算法 3-1. 基于程序上下文的 P4LTL 规范语义规约算法**

**输入：** P4LTL 规范 $S = \langle \mathcal{P}, \mathcal{F}_{\text{fair}}, \mathcal{V}, \mathcal{C}_{\text{cpi}} \rangle$，程序上下文 $C$，最大修正轮次 $k$

**输出：** 结构化任务规约 $Q$

---

1: **// 阶段一：时序逻辑分离与意图分类**

2: $\kappa \leftarrow \text{ClassifyIntent}(\mathcal{P}, C.\Sigma_{\text{src}})$ $\qquad$ // 根据性质模式识别测试类别

3: $\mu \leftarrow \text{DetermineGenerationMode}(\mathcal{C}_{\text{cpi}}, C.P_{\text{bmv2}})$ $\qquad$ // 有 CPI\_SPEC 则需生成控制面

4: $\mathcal{T}_{\text{trigger}} \leftarrow \text{ExtractTemporalTriggers}(\mathcal{P})$ $\qquad$ // 提取时序算子结构与状态转换条件

5:

6: **// 阶段二：原子命题分析与角色绑定**

7: $R_{\text{abstract}} \leftarrow \text{ExtractRolesFromAP}(\mathcal{P}, \mathcal{F}_{\text{fair}})$ $\qquad$ // 从 AP() 中提取逻辑角色

8: **for each** $r \in R_{\text{abstract}}$ **do**

9: $\quad h \leftarrow \text{BindToTopology}(r, C.T_{\text{topo}})$ $\qquad$ // 查询拓扑工具

10: $\quad R \leftarrow R \cup \{(r, h)\}$

11: **end for**

12:

13: **// 阶段三：场景构造与契约填充**

14: $A_{\text{op}} \leftarrow \text{InferEnvironmentActions}(\mathcal{P}, C.P_{\text{bmv2}})$ $\qquad$ // 推断隐含的外部操作前提

15: $O_{\text{obs}} \leftarrow \text{MapPredicatesToObservations}(\mathcal{P})$ $\qquad$ // drop/fwd/寄存器条件→观测需求

16: $\Lambda \leftarrow \emptyset$

17: **for each** property $\psi_i \in \mathcal{P}$ **do**

18: $\quad \sigma_i \leftarrow \text{DeriveScenarioFromProperty}(\psi_i, \mathcal{T}_{\text{trigger}})$ $\qquad$ // 性质→场景映射

19: $\quad \mathcal{S}_i \leftarrow \text{DecomposeToSteps}(\psi_i, \mathcal{F}_{\text{fair}}, C)$ $\qquad$ // 算子→步骤序列

20: $\quad \Phi_i \leftarrow \text{InferCrossStepConstraints}(\mathcal{S}_i, C.P_{\text{bmv2}})$ $\qquad$ // 查询字段位宽工具

21: $\quad \Lambda \leftarrow \Lambda \cup \{(\sigma_i, \mathcal{S}_i, \Phi_i)\}$

22: **end for**

23:

24: **// 阶段四：契约审查与修正**

25: $Q \leftarrow \langle \kappa, R, A_{\text{op}}, O_{\text{obs}}, \Lambda, \mu \rangle$

26: **for** $i = 1$ **to** $k$ **do**

27: $\quad \text{result} \leftarrow \text{ContractReview}(Q, C)$

28: $\quad$ **if** $\text{result.passed}$ **then break**

29: $\quad Q \leftarrow \text{RefineWithFeedback}(Q, \text{result.feedback}, C)$

30: **end for**

31: **return** $Q$

---

该算法分四步完成规约：第一，显式进行时序逻辑分离（第 4 行），将 P4LTL 的时序算子结构提取为状态转换条件，作为后续场景划分的依据；第二，从原子命题中提取角色信息（第 7 行），将 P4LTL 谓词中的 `meta.direction`、`standard_metadata.ingress_port` 等字段引用映射为逻辑角色；第三，将每条 `#LTLProperty` 映射为一个测试场景（第 17-22 行），并根据时序算子结构分解为有序步骤；第四，所有关键决策（角色绑定第 9 行、环境推断第 14 行、字段约束推断第 20 行）都通过工具查询获取程序证据。

**图 3-2 P4LTL 规范到 TaskSpec 的结构化分解过程**

> 图注：左列为 P4LTL 规范的四类输入组件，中列为三维分解过程（时序逻辑分离、控制面约束提取、数据面特征映射），右列为输出的 TaskSpec 六元组。底部虚线标注 ProgramContext 工具查询对分解过程的支撑。
