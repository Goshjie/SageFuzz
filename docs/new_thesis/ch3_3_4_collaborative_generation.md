# 3.3.4 多阶段协同生成与确定性校验

3.2.3 节通过快速重路由场景表明，可执行测试种子涉及数据面报文、控制面规则、外部操作和观测预言机等多个维度的输出，这些输出必须在语义上相互一致。为解决这一各维度间的一致性问题，P4-BISG 将生成过程拆分为多个角色明确的阶段，并在每个阶段设置确定性校验环节。本节首先给出确定性校验谓词的形式化定义，然后说明多阶段协同生成的编排算法，最后介绍回退机制。

### （1）确定性校验谓词

P4-BISG 的正确性保证不依赖于生成模型的一次性准确输出，而是建立在阶段间的确定性校验之上。系统对三类核心输出定义了形式化的校验谓词。

**定义 3.4（报文序列校验谓词）** 对场景 $\sigma$ 的报文序列 $\Pi_\sigma = \langle p_1, p_2, ..., p_m \rangle$，校验谓词定义为

$$V_{\text{packet}}(\Pi_\sigma, \sigma, C) = \bigwedge_{p \in \Pi_\sigma} \left[ V_{\text{proto}}(p) \wedge V_{\text{width}}(p, C) \wedge V_{\text{role}}(p, \sigma) \right]$$

其中三个子谓词分别检查：

- **协议栈合法性** $V_{\text{proto}}(p)$：报文的协议栈层级满足标准封装规则，例如 Ethernet $\rightarrow$ IPv4 $\rightarrow$ TCP 的层级关系成立。

$$V_{\text{proto}}(p) = \bigwedge_{l=1}^{|p.\text{stack}|-1} \text{IsValidTransition}(p.\text{stack}[l], p.\text{stack}[l+1])$$

- **字段位宽合法性** $V_{\text{width}}(p, C)$：报文中每个字段的取值不超出其位宽限制。

$$V_{\text{width}}(p, C) = \bigwedge_{f \in p.\mathcal{F}} \left[ 0 \leq p.f < 2^{C.w(f)} \right]$$

- **角色绑定一致性** $V_{\text{role}}(p, \sigma)$：报文的发送主机属于场景中已绑定的角色集合。

$$V_{\text{role}}(p, \sigma) = p.\text{txhost} \in h \mid (r, h) \in \sigma.R$$

**定义 3.5（控制面校验谓词）** 对控制面实体集合 $E$，校验谓词定义为

$$V_{\text{entity}}(E, C) = \bigwedge_{e \in E} \left[ e.\text{table} \in C.P_{\text{bmv2}}.\mathcal{T}.\text{names} \wedge e.\text{action} \in C.P_{\text{bmv2}}.A_{e.\text{table}} \right]$$

即每条规则引用的表和动作必须在目标程序的表签名集合中存在。进一步地，对规则参数的类型和位宽也进行校验：

$$V_{\text{param}}(E, C) = \bigwedge_{e \in E} \bigwedge_{(k, v) \in e.\text{match}} \left[ k \in C.P_{\text{bmv2}}.K_{e.\text{table}} \wedge 0 \leq v < 2^{C.w(k)} \right]$$

**定义 3.6（执行序列校验谓词）** 对执行序列 $\Xi = \langle \xi_1, \xi_2, ..., \xi_m \rangle$，校验谓词定义为

$$V_{\text{exec}}(\Xi) = \left[\bigwedge_{i=1}^{|\Xi|-1} \xi_i.\text{seq} < \xi_{i+1}.\text{seq}\right] \wedge \left[\bigwedge_{\xi \in \Xi} \xi.\text{type} \in \text{config}, \text{action}, \text{send}\right]$$

即序列编号严格递增，且每个操作的类型属于合法类型集合。

### （2）多阶段协同生成算法

算法 3-3 给出了 P4-BISG 的多阶段协同生成与校验调度流程。算法接收经过规约的 TaskSpec 和程序上下文，逐阶段生成报文序列、控制面规则和预言机预测，每个阶段在生成后立即执行确定性校验。

---

**算法 3-3. 多阶段协同生成与校验调度算法**

**输入：** 任务规约 $Q = \langle \kappa, R, A_{\text{op}}, O_{\text{obs}}, \Lambda, \mu \rangle$，程序上下文 $C$，最大重试次数 $k$

**输出：** 测试用例 $\text{TC} = \langle \Pi, E, \Xi, \Omega \rangle$

---

1: **// 阶段 A：报文序列构造与校验**

2: $\Pi \leftarrow \emptyset$

3: **for each** $(\sigma, \mathcal{S}, \Phi) \in \Lambda$ **do**

4: $\quad \Pi_\sigma \leftarrow \text{ConstructPacketSequence}(\sigma, \mathcal{S}, R, C)$ $\quad\triangleright$ 通过工具查询获取约束

5: $\quad$ **for** $i = 1$ **to** $k$ **do**

6: $\quad\quad$ **if** $V_{\text{packet}}(\Pi_\sigma, \sigma, C) \wedge V_{\text{contract}}(\Pi_\sigma, \mathcal{S}, \Phi)$ **then break** $\quad\triangleright$ 校验通过

7: $\quad\quad \Pi_\sigma \leftarrow \text{RepairSequence}(\Pi_\sigma, \text{violations}, C)$ $\quad\triangleright$ 阶段内修复

8: $\quad$ **end for**

9: $\quad$ **if** $\neg V_{\text{packet}}(\Pi_\sigma, \sigma, C)$ **then**

10: $\quad\quad \Pi_\sigma \leftarrow \text{FallbackMinimal}(\sigma, C)$ $\quad\triangleright$ 最小可执行回退

11: $\quad$ **end if**

12: $\quad \Pi \leftarrow \Pi \cup \Pi_\sigma$

13: **end for**

14:

15: **// 阶段 B：控制面规则生成与校验（条件执行）**

16: $E \leftarrow \emptyset$

17: **if** $\mu = \text{packetandentities}$ **then**

18: $\quad E \leftarrow \text{GenerateEntities}(Q, \Pi, C)$

19: $\quad$ **if** $\neg V_{\text{entity}}(E, C)$ **then**

20: $\quad\quad E \leftarrow \text{RepairEntities}(E, C, k)$

21: $\quad$ **end if**

22: **end if**

23:

24: **// 阶段 C：预言机预测**

25: $\Omega \leftarrow \text{PredictOracle}(Q, \Pi, C)$

26:

27: **// 阶段 D：执行序列组装与校验**

28: $\Xi \leftarrow \text{AssembleExecutionSequence}(E, \Pi, A_{\text{op}})$

29: **assert** $V_{\text{exec}}(\Xi)$

30:

31: $\text{TC} \leftarrow \langle \Pi, E, \Xi, \Omega \rangle$

32: **return** TC

---

### （3）回退机制

生成过程依赖模型输出时，结构不稳定是常态。P4-BISG 将系统稳定性建立在确定性校验与渐进回退之上，而非假设模型一次性输出正确。

回退策略遵循**渐进降级原则**：

1. **优先阶段内修复。** 当校验谓词检测到违规时（如字段位宽越界），系统首先尝试在当前阶段进行局部修复（算法 3-3 第 7 行），将违规信息作为修正上下文反馈给生成模块。
2. **其次最小可执行回退。** 当修复重试达到上限仍未通过校验时，系统生成最小可执行 testcase（第 10 行），保留场景结构和角色绑定，但使用默认的协议栈和最简字段值。
3. **始终保证可保存。** 回退策略的目标是保证 testcase 可保存、可回放、可追溯，即使语义上不完美，也能为后续的人工分析或迭代优化提供基础。

**图 3-4 多阶段协同生成流水线与校验反馈路径**

> 图注：横向展示四个生成阶段（A: 报文序列构造 → B: 控制面规则生成 → C: 预言机预测 → D: 执行序列组装），每阶段下方标注对应的确定性校验谓词（$V_{\text{packet}}$、$V_{\text{entity}}$、$V_{\text{oracle}}$、$V_{\text{exec}}$）。阶段间实线箭头携带结构化中间对象（PacketSequence、RuleEntities、OraclePrediction），虚线侧环箭头表示阶段内修复反馈路径。

