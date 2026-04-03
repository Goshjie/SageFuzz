# 3.3.3 程序上下文建模与证据查询

3.2.2 节通过链路监测场景表明，正确生成测试用例所需的约束分散在编译产物、控制流图、拓扑和有状态对象定义等多个异构数据源中。本节介绍 P4-BISG 中程序上下文层的设计，包括上下文的形式化定义、索引构建方法和工具化证据查询机制。

### （1）程序上下文的形式化定义

**定义 3.3（程序上下文）** 程序上下文 $C$ 定义为四元组

$$C = \langle P_{\text{bmv2}}, G_{\text{cfg}}, T_{\text{topo}}, \Sigma_{\text{src}} \rangle$$

各分量提供的证据查询能力如下：

**(a) 编译产物 $P_{\text{bmv2}}$** 由 BMv2 编译器输出的 JSON 文件和 P4Info 文件解析得到，提供以下索引结构：

$$P_{\text{bmv2}} = \langle \delta_{\text{parser}}, \mathcal{T}, w, \mathcal{S}_{\text{obj}} \rangle$$

其中 $\delta_{\text{parser}}$ 为解析器状态转移图，$\mathcal{T} = \{(t_i, K_{t_i}, A_{t_i})\}$ 为表签名集合（每个表包含匹配键集合 $K$ 和动作集合 $A$），$w: \mathcal{F} \rightarrow \mathbb{N}$ 为字段位宽函数，$\mathcal{S}_{\text{obj}}$ 为有状态对象（寄存器、计数器、计量器）集合。

**(b) 控制流图 $G_{\text{cfg}}$** 由编译输出的 DOT 文件解析并构建为有向图

$$G_{\text{cfg}} = (V, E)$$

其中节点集 $V$ 包含表节点和条件节点，边集 $E$ 表示控制流跳转关系。基于该图可导出表深度排序函数 $\text{rank}: V \rightarrow \mathbb{N}$ 和路径约束查询能力。

**(c) 拓扑信息 $T_{\text{topo}}$** 由拓扑 JSON 文件解析得到

$$T_{\text{topo}} = \langle \mathcal{H}, \mathcal{SW}, \mathcal{L}, \text{zone} \rangle$$

其中 $\mathcal{H}$ 为主机集合，$\mathcal{SW}$ 为交换机集合，$\mathcal{L}$ 为链路集合，$\text{zone}: \mathcal{H} \rightarrow \{\text{internal}, \text{external}, ...\}$ 为主机区域分类函数。

**(d) 可选源码 $\Sigma_{\text{src}}$** 为 P4 源代码文本，当意图涉及自定义头字段语义或特殊状态逻辑时，支持语义片段检索作为补充证据。

### （2）上下文索引构建

系统在初始化阶段通过确定性解析构建上下文索引。该过程不涉及模型推理，完全由确定性代码完成。算法 3-2 描述了索引构建流程。

---

**算法 3-2. 程序上下文索引构建算法**

**输入：** BMv2 JSON 文件 $F_{\text{json}}$，DOT 文件 $F_{\text{dot}}$，拓扑文件 $F_{\text{topo}}$，P4 源码 $F_{\text{src}}$（可选）

**输出：** 程序上下文 $C$

---

1: **// 编译产物索引构建**

2: $\delta_{\text{parser}} \leftarrow \text{ParseParserDAG}(F_{\text{json}})$

3: $\mathcal{T} \leftarrow \text{ExtractTableSignatures}(F_{\text{json}})$ $\quad\triangleright$ 表名→匹配键→动作映射

4: $w \leftarrow \text{BuildFieldWidthIndex}(F_{\text{json}})$ $\quad\triangleright$ 字段名→位宽映射

5: $\mathcal{S}_{\text{obj}} \leftarrow \text{ExtractStatefulObjects}(F_{\text{json}})$

6: $P_{\text{bmv2}} \leftarrow \langle \delta_{\text{parser}}, \mathcal{T}, w, \mathcal{S}_{\text{obj}} \rangle$

7:

8: **// 控制流图构建**

9: $G_{\text{cfg}} \leftarrow \text{LoadAndParseGraph}(F_{\text{dot}})$

10: $\text{rank} \leftarrow \text{ComputeTopologicalRank}(G_{\text{cfg}})$

11:

12: **// 拓扑索引构建**

13: $(\mathcal{H}, \mathcal{SW}, \mathcal{L}) \leftarrow \text{ParseTopology}(F_{\text{topo}})$

14: $\text{zone} \leftarrow \text{ClassifyHostZones}(\mathcal{H}, \mathcal{SW}, \mathcal{L})$

15: $T_{\text{topo}} \leftarrow \langle \mathcal{H}, \mathcal{SW}, \mathcal{L}, \text{zone} \rangle$

16:

17: **// 可选源码索引**

18: $\Sigma_{\text{src}} \leftarrow \text{IndexSourceCode}(F_{\text{src}})$ **if** $F_{\text{src}} \neq \text{null}$

19:

20: **return** $C = \langle P_{\text{bmv2}}, G_{\text{cfg}}, T_{\text{topo}}, \Sigma_{\text{src}} \rangle$

---

### （3）工具化证据查询机制

P4-BISG 的核心设计原则之一是生成模块不直接读取原始编译产物文本，而是通过标准化的工具接口按需获取小片段证据。这种设计有两个关键优势：一方面减少了无关上下文对生成模型的干扰；另一方面使每个生成决策可追溯到具体的程序证据。

形式化地，工具化查询定义为函数

$$\text{Query}: \mathcal{Q}_{\text{type}} \times C \times \text{params} \rightarrow \text{evidence}$$

其中 $\mathcal{Q}_{\text{type}}$ 为查询类型集合。表 3-2 列出了系统支持的主要查询类型及其与上下文分量的映射关系。

**表 3-2 工具化查询类型与证据来源**

| 查询类型 | 输入参数 | 证据来源 | 返回内容 |
|---------|---------|---------|---------|
| PARSER\_PATH | 目标头字段 | $\delta_{\text{parser}}$ | 到达该头字段的解析路径与转移条件 |
| TABLE\_SIGNATURE | 表名称 | $\mathcal{T}$ | 匹配键集合、动作集合与参数类型 |
| FIELD\_WIDTH | 字段名称 | $w$ | 字段位宽（比特数） |
| STATEFUL\_OBJECT | 对象名称 | $\mathcal{S}_{\text{obj}}$ | 对象类型、大小与索引方式 |
| HOST\_ROLE | 逻辑角色、区域 | $T_{\text{topo}}$ | 满足条件的主机列表及接入信息 |
| CFG\_CONSTRAINT | 源节点、目标节点 | $G_{\text{cfg}}$ | 路径约束条件与经过的表列表 |
| TABLE\_RANKING | — | $G_{\text{cfg}}$ | 按拓扑排序的表深度排列 |
| SOURCE\_SEMANTIC | 关键词 | $\Sigma_{\text{src}}$ | 相关源码片段与上下文 |

**图 3-3 程序上下文工具查询架构**

> 图注：左侧为各生成模块，中间为 ProgramContext 统一查询调度器（支持 PARSER_PATH、TABLE_SIGNATURE、FIELD_WIDTH 等查询类型），右侧为四类数据源（BMv2 Index / CFG Graph / Topology Index / Source Index）。实线表示查询请求，虚线表示证据返回。

这种工具化查询设计与 3.2.2 节中分析的挑战直接对应。以链路监测程序为例，序列构造模块在生成 probe 报文时：首先通过 PARSER\_PATH 查询获取 `probe_header` 的解析路径与先决条件；然后通过 FIELD\_WIDTH 查询确定各探针字段的位宽；接着通过 STATEFUL\_OBJECT 查询获取 `byte_cnt_reg` 的索引方式；最后通过 HOST\_ROLE 查询确定 probe 应从哪个主机注入。整个过程中，生成模块无需处理完整的编译产物文本，只需发起四次精确查询即可获取所有必要约束。
