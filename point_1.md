# 面向网络行为的 P4 意图感知与种子生成技术

## 一、整体流程：

1. 接收到java端发送的seed_generate命令后，驱动多智能体架构启动
2. **系统初始化加载（DOT/JSON/P4Info/Topology）→ 多智能体通过工具实时调用生成 input pkt 序列（本期优先实现该部分；entities 可后续实现）**
3. 将步骤2生成的input发给P4CE，生成初步的output pkt
4. 将步骤3生成的output pkt交给enhanced oracle生成正确的output pkt
5. 保存完整生成的testcase

## 二、多智能体可使用工具

### 0）系统初始化与上下文驻留（非智能体“输入上下文”）

为最大限度降低 LLM 幻觉风险，本系统不将大量“编译产物/拓扑信息”以长文本形式塞给智能体，而是由**系统主控调度器在启动阶段确定性加载并驻留到内存**（ProgramContext），随后智能体仅通过工具（tool）进行**实时查询**并基于工具返回的证据进行推理与生成。

以 `P4/firewall/build/` 为例，初始化阶段应加载并索引：

- **控制流/拓扑图（DOT）**：`build/graphs/*.dot`（例如 `MyIngress.dot`、`MyParser.dot`），用于 CFG/表跳转、路径约束等工具查询（推荐使用 NetworkX 加载到内存图结构）。
- **BMv2 编译产物（JSON）**：`build/firewall.json`，用于解析器状态机、header 位宽、actions/tables/stateful objects 等工具查询。
- **P4Info（txtpb）**：`build/firewall.p4.p4info.txtpb`，用于表结构、动作参数签名等权威信息查询。
- **拓扑（Topology）**：例如 `pod-topo/topology.json`，用于主机 IP/MAC、链路、host 角色（internal/external）以及每个数据包的发送者绑定（`tx_host`）等工具查询。

> 关键原则：智能体一（以及后续所有智能体）默认**没有**“输入上下文大段文本”；它们只知道“可用工具列表 + 输出契约”，并在需要时通过工具获取最小、可验证的证据片段。

### 智能体感知工具链 (Agent Perception Toolchain)

为使大语言模型（LLM）能够精准推演 P4 程序的网络意图并生成高维度的多包测试序列，本系统设计了一套分层解耦的工具链。该工具链分为“控制流拓扑解析”与“底层代码语义提取”两大模块，为智能体提供全方位的程序上下文感知能力。

#### （1）NetworkX 解析的控制流图 (CFG/Graph)：

**定位：程序的“骨架与神经”**，主要负责宏观路径规划、状态机推演与约束求解。大模型通过调用此类工具，了解数据包在流水线中的“游走规则”。

  **`get_jump_dict()` (控制流跳转字典提取)**

- **作用：** 返回流水线中表与表之间（Table-to-Table）或控制节点之间的跳转映射关系。
- **意图赋能：** 帮助 LLM 理解程序的宏观逻辑走向（例如：如果命中 Table A 的 `action X`，下一步会跳转到 Table B 还是直接 `Drop`）。

**`get_parser_paths()` (解析器状态机全量路径生成)**

- **作用：** 遍历解析器（Parser）树，返回所有合法的协议解析路径组合（如 `Ethernet -> IPv4 -> TCP` 或 `Ethernet -> ARP`）。
- **意图赋能：** 指导 LLM 确定初始数据包（Input Pkt）的基础协议封装结构，避免生成在入口处就被丢弃的畸形包。

**`get_parser_transitions()` (解析器分支条件提取)**

- **作用：** 精确获取解析器中触发状态转移的匹配条件（如 `transition select(hdr.ethernet.etherType) { 16w0x0800: parse_ipv4; }`）。
- **意图赋能：** 让 LLM 知道在生成特定协议序列时，必须将底层报文的某个特定字段（如 EtherType 或 IP Protocol）设置为精确的魔法值（Magic Number）。

**`get_path_constraints()` (深层路径约束求解器接口) 🔥核心工具**

- **作用：** 给定一个目标节点（如最深处的有状态业务表），逆向推导出到达该节点必须满足的全局条件（包括 Metadata 状态和 Header 字段要求）。
- **意图赋能：** 解决传统 Fuzzing 的“路径爆炸”难题，LLM 直接拿到“通关秘籍”，从而精准构造能打穿复杂逻辑流的种子包。

**`get_ranked_tables()` (流表拓扑深度排序)**

- **作用：** 基于有向无环图（DAG）的拓扑排序算法，计算并返回所有表节点的执行深度权重。
- **意图赋能：** 引导 LLM 优先关注深度最深、业务逻辑最复杂的表（往往是有状态操作的集中地），将漏洞挖掘火力集中在核心意图上。

**`get_table()` (单表属性高精度提取)**

- **作用：** 传入指定的 Table 名称，返回其详细属性，包括匹配键（Match Keys，如 `hdr.ipv4.dstAddr: lpm`）、支持的动作列表（Actions）及表容量（Size）。
- **意图赋能：** LLM 生成控制面规则（Entities/Rules）的直接依据，确保生成的测试规则 100% 符合硬件结构约束。

**`get_tables()` (全局流表清单盘点)**

- **作用：** 宏观扫描全量控制块（Control Block），返回所有实例化的 Table 列表。
- **意图赋能：** 帮助智能体（如语义分析师 Agent）在初期快速摸底程序的规模与功能模块构成。

**`get_header_bits()` (报文字段位宽精准计算)**

- **作用：** 返回任意 Header 字段在二进制流中的精确位宽（Bit-width）与偏移量（Offset）。
- **意图赋能：** 为后续调用 Scapy 进行底层二进制实例化组装时，提供精确的数据类型对齐依据，防止因长度溢出导致的解析失败。

#### （2.5）拓扑与发送者绑定工具 (Topology & Host Mapping)

在很多面向网络行为的测试中，**“哪个 host 发包/哪个 host 回包”**是触发状态机与方向性策略的关键条件（例如防火墙只允许 internal 发起、external 只能回复）。因此需要提供拓扑查询工具，避免智能体凭空编造 host/IP/MAC。

建议工具接口（示例）：

- **`get_topology_hosts()`**：返回所有 host 及其 IP/MAC（例如 `h1..h4`）。
- **`get_topology_links()`**：返回拓扑链路列表（host-交换机端口、交换机互联等）。
- **`get_host_info(host_id)`**：查询指定 host 的 IP/MAC/初始化命令等。
- **`classify_host_zone(host_id)`**：将 host 归类为 `internal/external`（证据来源必须可追溯，如 topology.json 的网段/显式标注）。
- **`choose_default_host_pair()`**：在缺少更强约束时，确定默认的 internal/external host 角色对，用于最小可复现的时序状态测试用例生成。

#### （2）基于 P4 源码/AST 的语义提取工具

**定位：程序的“肌肉与记忆”**。由于 CFG 图无法展现具体的赋值运算和状态存储，此模块通过直接提取代码块与状态定义，补全 LLM 的微观语义认知。

**`get_action_code(action_name)` (动作核心逻辑提取)**

- **作用：** 越过表结构，直接提取目标 Action 内部的原始 P4 语句（如加减运算、字段重写、校验和更新等赋值操作）。
- **意图赋能：** 让 LLM 看透动作的“本质”。例如，通过识别 `hdr.ipv4.srcAddr = new_ip;`，LLM 才能断定这是一个 NAT 意图，从而在预言机中制定相应的地址校验策略。

**`get_stateful_objects()` (持久化状态对象发现) 🔥状态核心工具**

- **作用：** 扫描全局，提取所有的 `register`（寄存器）、`meter`（测量器）和 `counter`（计数器）的实例化定义及其位宽。
- **意图赋能：** Fuzzing 框架发现“网络记忆”的雷达。一旦检测到状态对象，LLM 即可判定该程序为 Stateful NFV，从而强制要求自身生成**多包事务序列（Multi-packet sequence）**来验证状态机跃迁。

**`get_header_definitions()` (结构体与元数据定义提取)**

- **作用：** 直接返回 P4 源码中关于 `struct metadata` 和 `header` 的完整代码块。
- **意图赋能：** 当 `get_path_constraints()` 返回一个晦涩的元数据变量（如 `meta.fwd_type`）时，LLM 可借此工具查阅其类型与业务含义，完善脑内的协议推演闭环。

### （3）测试用例实例化与制品构建工具

**定位：抽象意图的“降维与物理具象化”**。大语言模型输出的意图虽然在逻辑上自洽，但属于高度抽象的声明式语义（如 JSON 格式），无法被底层的 P4 执行引擎（如 P4CE 或 p4testgen）直接识别。本模块负责跨越“语义鸿沟”，将抽象架构转化为底层引擎可严格执行的二进制制品与测试场景。

> 工程落地备注（阶段性范围）：当前阶段可先只实现“生成可读的 packet_sequence JSON（并绑定 tx_host/topology）”，暂不强求落地 `convert_to_executable_format()`/P4CE 下发/oracle/merge 等外置模块集成。

**1. `convert_to_executable_format()` (底层执行格式序列化工具 / 格式转换 Tool)**

- **作用：** 专职负责“数据面（Data Plane）”报文的降维与实例化。接收序列构造智能体（Agent 2）生成的结构化报文 JSON，调用内置的 Scapy 引擎将其具象化。工具自动完成网络层的校验和（Checksum）重算、报文长度填充及首部对齐，并最终剥离为底层执行器（如 P4CE）所需的十六进制字节流（Hex Stream）或 PCAP 文件。

  **意图赋能：** 作为连接大模型虚拟语义与底层物理网络的唯一“数据翻译官”，彻底隔离了 LLM 在比特级精密计算上的“幻觉风险”，确保所有注入测试流的数据包 100% 具备物理合法性。

**`merge_testcase_scenario()` (多维测试场景组装与聚合工具 / 合并 Tool)**

- **作用：** 将离散的测试元素进行时序绑定与空间聚合。该工具将序列化后的**输入报文序列（Input Pkt Sequence）**、对应的**控制面流表实体（Entities/Rules）**，以及（通过基线预执行或增强预言机获取的）**预期输出报文（Expected Output Pkt）**，严格按照时序依赖关系，合并封装为一个原子化的标准测试场景文件（如 `.stf` 脚本或定制的 `Scenario_JSON` 包）。
- **意图赋能：** 重新定义了模糊测试的“种子”边界。它将传统的“单包触发器”升级为包含完整上下文逻辑的“事务级测试用例（Transaction-level Testcase）”。通过将输入、规则与预期输出强制聚合为一个不可分割的黑盒实体，不仅确保了状态机推演过程中的时序一致性，也为后续意图引导下的动态变异阶段（Mutation Phase）提供了绝对稳固的基准参考准星（Ground Truth）。



## 三、 多智能体架构设计

### 系统主控调度器 (System Master Orchestrator) —— “确定性中枢与总线指挥官”

在多智能体协同架构中，为了抑制大语言模型（LLM）固有的不可预测性与流程控制幻觉，本系统创新性地引入了基于**纯逻辑代码（Pure Deterministic Code）**的系统主控调度器。它不是大模型智能体，而是整个架构的“确定性状态机”与总线总控引擎。

- **核心职责：** 系统级 I/O 交互、智能体生命周期管理、结构化任务解析与分发、双轨异步流的同步阻塞，以及物理工具链的精确调用。
- **组件性质：** 确定性工作流编排引擎（Deterministic Workflow Orchestration Engine）。
- **输入 (Input)：** 1. 外部 Java 控制端下发的 `seed_generate` 指令。 2. 智能体一（语义分析师）返回的严格 JSON 格式任务清单（Task List）。
- **工作逻辑（基于 JSON 契约的通信与路由）：**
  1. **任务触发与解析：** 接收生成指令后，唤醒智能体一对 P4 源码进行推演，并强制其输出基于 JSON 契约的分析结果。主控调度器利用标准 JSON 解析器提取出全局意图与原子化的任务单元。
  2. **级联数据流注入 (Cascaded Data Flow Injection)：** 摒弃容易导致状态不一致的纯并行生成，调度器采用严格的先后时序：先驱动数据面轨道（Agent 2）生成具体报文，随后将该报文的物理特征（如生成的具体 IP 地址）作为上下文变量，动态注入到控制面轨道（Agent 4）的提示词模板中。
  3. **节点阻塞与重试：** 在每个智能体节点（Agent 3 和 Agent 5）设置审查关卡。只有当审查员返回合规的 `PASS` 信号时，状态机才允许向下流转；若返回 `FAIL`，则调度器触发带有错误日志的重试循环。
  4. **物理调用与闭环：** 剥夺 LLM 的执行权，由主控调度器直接调用 `convert_to_executable_format()`、下发底层执行引擎指令、挂载预言机（Oracle）进行状态校准，并最终调用 `merge_testcase_scenario()`。
- **输出 (Output)：** 组装完毕的标准测试用例包（Testcase Scenario），并向外部系统返回执行成功状态。
- **架构价值：** 确立了“以确定性代码控制骨架，以概率性智能体填充血肉”的混合架构原则。彻底消除了复杂任务拆解过程中的语义漂移，保障了底层系统工具（如进程唤醒、文件读写）执行时的绝对工程鲁棒性。

### 智能体一：语义分析师 (Semantic Analyzer Agent)

这是整个系统的“大脑”，负责宏观上的战略规划。它不需要关心报文长什么样，重点是看懂程序的网络架构与状态机。

- **核心职责：** 意图提取与测试任务规划。
- **输入 (Input)：** **无默认“上下文文本输入”**。系统初始化阶段已将 DOT/JSON/P4Info/Topology 加载进 ProgramContext；语义分析师在运行时通过工具链实时调用获取证据（例如 `get_stateful_objects()`、`get_ranked_tables()`、`get_path_constraints()`、`get_parser_paths()`、`get_topology_hosts()` 等）。
- **依赖工具链 (Required Tools)：**
  - `get_tables()`：快速盘点全局表结构，摸底程序规模。
  - `get_ranked_tables()`：精准定位深度最深、逻辑最复杂的核心业务表。
  - `get_stateful_objects()`：🔥**核心工具**。扫描寄存器和计数器，判定程序是否具备“状态记忆”，决定是否需要生成多包事务序列。
  - `get_path_constraints()`：逆向推导目标业务表的全局约束条件，了解业务触发逻辑。
  - `get_jump_dict()`：理解控制流块之间的宏观跳转关系。
- **工作逻辑：** 它不写任何具体的数据包参数。它像一个网络架构师一样，阅读代码并调用上述工具后，总结出这个程序的业务意图，并拆解出必须覆盖的测试任务清单（Task List）。

### 智能体二：序列构造师 (Sequence Constructor Agent) —— “领任务，写剧本”

这是数据面轨道的“苦力”，它负责把抽象的测试任务变成具体的、结构化的数据包 JSON。

- **核心职责：** 基于测试任务，生成多包事务序列（JSON 格式）。
- **输入 (Input)：** 智能体一输出的某一个“测试任务” + P4 解析器拓扑证据。
- **依赖工具链 (Required Tools)：**
  - `get_parser_paths()`：确定合法的协议栈堆叠顺序（如 Ethernet -> IPv4 -> TCP）。
  - `get_parser_transitions()`：获取状态转移的魔法值（Magic Number），例如确保生成的 JSON 中 EtherType 是 `0x0800` 以顺利进入 IPv4 解析。
  - `get_header_definitions()`：查阅头部具体包含哪些字段（如 TCP 包含 flags, seq, ack）。
  - `get_header_bits()`：获取字段位宽，确保生成的数值不越界。
- **工作逻辑：** 依据网络协议常识与解析器约束，生成符合特定路径走向的结构化载荷。在处理有状态任务时，内部维护“虚拟状态机”，确保生成的序列号和确认号在逻辑上连续。

### 智能体三：input pkt逻辑审查员 (Constraint Critic Agent) —— “找茬，防幻觉”

这是保证数据面不出低级 Bug 的最后一道防线。

- **核心职责：** 校验智能体二生成的 JSON 的语法与基础协议语义约束。
- **输入 (Input)：** 智能体二生成的报文 JSON。
- **依赖工具链 (Required Tools)：**
  - `get_parser_paths()` & `get_parser_transitions()`：作为“判卷标准”，核对智能体二生成的报文路径与状态转移条件是否与 P4 源码真实逻辑 100% 贴合。
- **工作逻辑：** 它不负责生成，只负责“挑刺”。比如，发现智能体二未满足某条 transition 条件，或者把 `tcp_flags` 写成了不合法的字符串，审查员就会附带工具返回的正确标准打回重做。
- **输出 (Output)：** `PASS` 或 `FAIL + 修复意见`。

### 智能体四：控制面规则生成师 (Control-Plane Entity Generator Agent)

- 控制面轨道的核心。它不仅负责打通流水线，更实现了跨平面的严密对齐。

  - **核心职责：** 基于全局意图与数据包序列，生成匹配-动作表项（Match-Action Entities）。
  - **输入 (Input)：** 智能体一输出的【宏观测试意图】 + 智能体二/三生成的【已合法化数据包 JSON】。
  - **依赖工具链 (Required Tools)：**
    - `get_table(table_name)`：🔥**核心工具**。传入目标表名，精准获取该表需要的 Match Keys 类型（如 exact, lpm, ternary）以及允许调用的 Action 列表。
    - `get_action_code(action_name)`：获取动作底层的赋值逻辑，从而决定传入什么参数（如发现动作包含 `dstAddr = new_ip`，便知道需要生成 `new_ip` 参数）。
  - **工作逻辑：** 接收到前面生成的具体数据包（如源 IP 为 `10.0.0.5`）后，提取该特征作为 Match Key（保证 100% 命中）。同时，依据宏观意图（如“NAT 转换”），智能推演出传统脚本无法生成的复杂 Action 参数（如 `new_ip: 192.168.1.1`）。

- **输出示例 (Output JSON)：**

  JSON

  ```
  entities {
    table_entry {
      table_id: 41243186
      table_name: "FabricIngress.stats.flows"
      match {
        field_id: 6
        field_name: "ig_port"
        exact {
          value: "\000\010"
        }
      }
      match {
        field_id: 3
        field_name: "ip_proto"
        ternary {
          value: "\006"
          mask: "\006"
        }
      }
      match {
        field_id: 2
        field_name: "ipv4_dst"
        ternary {
          value: "\377\377\377\377"
          mask: "\377\377\377\377"
        }
      }
      match {
        field_id: 1
        field_name: "ipv4_src"
        ternary {
          value: "\377\337\377\337"
          mask: "\377\337\377\337"
        }
      }
      match {
        field_id: 5
        field_name: "l4_dport"
        ternary {
          value: "\377\377"
          mask: "\377\377"
        }
      }
      match {
        field_id: 4
        field_name: "l4_sport"
        ternary {
          value: "\377\377"
          mask: "\377\377"
        }
      }
      action {
        action {
          action_id: 21929788
          action_name: "FabricIngress.stats.count"
          params {
            param_id: 1
            param_name: "flow_id"
            value: "\000\000"
          }
        }
      }
      priority: 200
      is_valid_entry: 1
    }
  }
  entities {
    table_entry {
      table_id: 34606298
      table_name: "FabricIngress.slice_tc_classifier.classifier"
      match {
        field_id: 1
        field_name: "ig_port"
        ternary {
          value: "\000\010"
          mask: "\000\010"
        }
      }
      match {
        field_id: 4
        field_name: "ip_proto"
        ternary {
          value: "\006"
          mask: "\006"
        }
      }
      match {
        field_id: 3
        field_name: "ipv4_dst"
        ternary {
          value: "\377\377\377\377"
          mask: "\377\377\377\377"
        }
      }
      match {
        field_id: 2
        field_name: "ipv4_src"
        ternary {
          value: "\377\377\377\377"
          mask: "\377\377\377\377"
        }
      }
      match {
        field_id: 6
        field_name: "l4_dport"
        ternary {
          value: "\377\377"
          mask: "\377\377"
        }
      }
      match {
        field_id: 5
        field_name: "l4_sport"
        ternary {
          value: "\377\377"
          mask: "\377\377"
        }
      }
      action {
        action {
          action_id: 23786376
          action_name: "FabricIngress.slice_tc_classifier.set_slice_id_tc"
          params {
            param_id: 1
            param_name: "slice_id"
            value: "\000"
          }
          params {
            param_id: 2
            param_name: "tc"
            value: "\000"
          }
        }
      }
      priority: 200
      is_valid_entry: 1
      matched_idx: 1
    }
  }
  ```

### 智能体五：实体规则合规审查员 (Entity Compliance Critic Agent)

控制面的“质检员”。一旦下发给 P4 交换机的表项（Entities）格式错误，底层交换机会直接 CLI 崩溃，导致 Fuzzing 中断。

- **核心职责：** 针对生成的 Entities 进行严格的语法与约束校验，防止 LLM 的控制面表项幻觉。
- **输入 (Input)：** 智能体四生成的 Entities JSON。
- **依赖工具链 (Required Tools)：**
  - `get_table(table_name)`：调取权威的表结构定义模板。
  - `get_action_code(action_name)`：调取动作的参数签名。
- **工作逻辑（找茬模式）：**
  - **表与动作校验：** 核实 P4 程序中是否真实存在该表，以及该动作是否合法挂载于此表下。
  - **匹配键校验：** 如果源码要求 `dstAddr` 是 `lpm`（最长前缀匹配），审查员会检查 Entities JSON 中是否错写成了 `exact`。
  - **参数校验：** 检查动作所需参数个数与类型是否严格对齐。
- **输出 (Output)：** `PASS` 或 `FAIL + 修复意见`（例如：“错误：`ipv4_lpm` 表的匹配键缺少掩码长度，请补充。” -> 打回重构）。

### 智能体六：拓扑与发送者分配师 (Topology & Sender Assigner Agent)

很多面向网络行为的测试用例，其关键不在于“包长什么样”，而在于**谁先发起、谁只能回复、以及每个包由拓扑中的哪个 host 发送**。例如防火墙场景中，常见策略是：**internal 可发起连接，external 只能作为 server 端回复**。

- **核心职责：** 将已生成的数据包序列与控制面规则（Entities/Rules）绑定到具体拓扑，明确每个数据包的发送者（`tx_host`），并可扩展推导 ingress_port/链路路径等运行时绑定信息。
- **输入 (Input)：** 智能体二/三输出的 `packet_sequence` + 智能体四/五输出的 Entities（如果已实现）+ Topology（hosts/links）。
- **依赖工具链 (Required Tools)：**
  - `get_topology_hosts()` / `get_topology_links()` / `get_host_info(host_id)`：获取 host/IP/MAC 与链路。
  - `classify_host_zone(host_id)`：确定 internal/external 角色归类。
  - （可选）`get_jump_dict()` / `get_path_constraints()`：辅助推断从 host 到目标表路径的可能性。
- **输出 (Output)：** 在 JSON testcase 中为每个 packet 填充 `tx_host`（例如 `h1`/`h3`），并输出 `topology_ref` 以保证可复现。
- **阶段性说明：** 若当前工程阶段尚未实现 Agent6，可先由主控调度器按默认规则（基于 topology 工具证据）为 packet_sequence 填充 `tx_host` 占位值；后续再用 Agent6 替换为更精确的智能绑定。



## 四、智能体交互流程

### 系统全局运行工作流 (Global System Workflow)

本系统的意图感知种子生成阶段，采用**“主控编排、双轨并行、闭环校准”**的设计哲学。整个生命周期由系统主控调度器（确定性代码）驱动，多名 LLM 智能体与底层物理引擎协同工作。具体运行流程可划分为以下核心阶段：

#### 阶段零：系统初始化与上下文加载 (ProgramContext Initialization)

1. **加载编译产物与拓扑：** 主控调度器确定性加载 DOT（CFG/Graph）、BMv2 JSON、P4Info（txtpb）与 Topology（hosts/links）。
2. **建立索引与工具注册：** 将上述工件驻留到内存 ProgramContext，并注册成可被智能体实时查询的 tool 接口（工具输出需要可追溯证据来源）。
3. **原则约束：** 后续智能体推理与生成必须以 tool 返回的证据为依据，避免“长上下文输入导致的幻觉与漂移”。

#### 阶段一：任务触发与宏观意图推演 (Initialization & Intent Inference)

1. **指令下发：** 外部 Java 控制端向 Fuzzing 框架发送 `seed_generate` 启动指令。
2. **中枢接管：** 系统主控调度器（Orchestrator）接管流程，唤醒**智能体一（语义分析师）**。
3. **工具调用与扫图：** 智能体一调用宏观工具（如 `get_path_constraints`、`get_stateful_objects`、`get_ranked_tables`、`get_topology_hosts`）对已加载的 ProgramContext 进行证据化扫描，推断程序的网络状态记忆与核心业务意图。
4. **任务拆解：** 智能体一输出严格的 JSON 契约，将全局意图拆解为多个原子化的【测试任务】（包含数据面预期与控制面预期），交还给调度器。

#### 阶段二：数据面先行生成与对抗审查 (Data-Plane Generation & Critic)

- 1. **报文构造：** 调度器将任务下发至**智能体二（序列构造师）**，推演出结构化的多包事务序列（Input Pkt JSON）。

     **逻辑质检：** 报文流转至**智能体三（审查员）**。若比对发现协议字段或状态跃迁条件错误（`FAIL`），则附带工具反馈打回重构；直至审查输出 `PASS`。

#### 阶段三：级联特征注入与语义规则生成 (Cascaded Feature Injection & Semantic-HGRG)

1. **特征注入：** 调度器提取已通过审查的数据包 JSON，连同原始宏观意图，一并作为上下文注入到**智能体四（规则生成师）**的推演流中。
2. **规则推演：** 智能体四充当 Semantic-HGRG，提取包头物理特征构建精准 Match Keys，并依据意图推演 Action 复杂参数，生成 Entities JSON。
3. **合规质检：** 规则流转至**智能体五（审查员）**。若发现匹配键类型或动作参数产生幻觉，则打回重构；直至输出 `PASS`。

#### 阶段四：物理降维实例化与预言机校准 (Physical Instantiation & Oracle Calibration)

1. **物理翻译：** 调度器剥夺 LLM 执行权，调用 **`convert_to_executable_format()`**。将高维报文 JSON 实例化为十六进制字节流（自动补齐校验和），并将 Entities JSON 编译为底层交换机 CLI 指令串。
2. **基线执行：** 将报文与 CLI 规则下发至 P4CE 执行引擎，进行一轮预运算，获取初步输出报文。
3. **状态注入与校准：** 调度器挂载手写的**增强型预言机（Enhanced Oracle）**，对初步输出进行检查与修正，生成 100% 正确的“判定基准（Intent Baseline / $\hat{y}$）”。

#### 阶段五：终极封包与基准落盘 (Testcase Packaging & Persistence)

1. **时序绑定：** 主控调度器调用 **`merge_testcase_scenario()`** 工具。
2. **封包落盘：** 将实例化输入报文 $x$、控制面实体规则 $c$、初始状态 $\sigma$ 以及预言机校准后的预期输出 $\hat{y}$，按严格时序强绑定，打包成标准的测试用例文件（如 `.stf` 脚本）。
3. **任务终结：** 向 Java 端返回“生成成功”信号，该四元组 $\tilde{s}$ 正式入库，成为后续动态变异阶段的核心基准。



## 智能体交互格式示例

### 1. 智能体一：语义分析师 (Semantic Analyzer)

**场景：** 经过对 ProgramContext（DOT/JSON/P4Info/Topology）工具查询的证据化分析，它决定生成一个合法的 TCP 握手序列，以触发防火墙的时序状态（并体现方向性策略：internal 可发起，external 只能回复）。

JSON

```
{
  "topology_ref": "P4/firewall/pod-topo/topology.json",
  "global_intent": "Stateful Firewall Test: verify directional TCP connection tracking (internal initiates, external only replies).",
  "task_list": [
    {
      "task_id": "T01_DIRECTIONAL_TCP_HANDSHAKE",
      "task_description": "Positive: h1 (internal) initiates TCP to h3 (external), h3 replies. Optional negative: h3 cannot initiate TCP to h1.",
      "data_plane_intent": "Generate a minimal TCP handshake-like sequence that can trigger time-ordered state: SYN (h1->h3), SYN-ACK (h3->h1), ACK (h1->h3). Optionally add a negative SYN (h3->h1).",
      "topology_intent": "Bind each packet to a sender host (tx_host) from topology: h1 is internal client, h3 is external peer (reply-only).",
      "control_plane_intent": "Insert routing rules in ipv4_lpm table to forward internal subnet traffic to port 2, and external subnet traffic to port 1."
    }
  ]
}
```

**调度器动作：** 纯代码主控调度器读取这个 JSON，把 `task_list[0]` 里的 `data_plane_intent` 提取出来发给智能体二，把 `control_plane_intent` 发给智能体四。

------

### 2. 智能体二：序列构造师 (Sequence Constructor)

**场景：** 接收到 `data_plane_intent` 后，它调用协议解析工具，输出 Scapy 能够无缝解析的结构化报文字典。

JSON

```
{
  "task_id": "T01_DIRECTIONAL_TCP_HANDSHAKE",
  "packet_sequence": [
    {
      "packet_id": 1,
      "tx_host": "h1",
      "protocol_stack": ["Ethernet", "IPv4", "TCP"],
      "fields": {
        "Ethernet.src": "08:00:00:00:01:11",
        "Ethernet.dst": "08:00:00:00:03:33",
        "Ethernet.etherType": "0x0800",
        "IPv4.src": "10.0.1.1",
        "IPv4.dst": "10.0.3.3",
        "IPv4.proto": 6,
        "TCP.sport": 12345,
        "TCP.dport": 80,
        "TCP.flags": "S",
        "TCP.seq": 1000
      }
    },
    {
      "packet_id": 2,
      "tx_host": "h3",
      "protocol_stack": ["Ethernet", "IPv4", "TCP"],
      "fields": {
        "Ethernet.src": "08:00:00:00:03:33",
        "Ethernet.dst": "08:00:00:00:01:11",
        "Ethernet.etherType": "0x0800",
        "IPv4.src": "10.0.3.3",
        "IPv4.dst": "10.0.1.1",
        "IPv4.proto": 6,
        "TCP.sport": 80,
        "TCP.dport": 12345,
        "TCP.flags": "SA",
        "TCP.seq": 5000,
        "TCP.ack": 1001
      }
    },
    {
      "packet_id": 3,
      "tx_host": "h1",
      "protocol_stack": ["Ethernet", "IPv4", "TCP"],
      "fields": {
        "Ethernet.src": "08:00:00:00:01:11",
        "Ethernet.dst": "08:00:00:00:03:33",
        "Ethernet.etherType": "0x0800",
        "IPv4.src": "10.0.1.1",
        "IPv4.dst": "10.0.3.3",
        "IPv4.proto": 6,
        "TCP.sport": 12345,
        "TCP.dport": 80,
        "TCP.flags": "A",
        "TCP.seq": 1001,
        "TCP.ack": 5001
      }
    }
  ]
}
```

**设计巧思：** 注意 `TCP.flags` 用的是 `"S"`（SYN）、`"SA"`（SYN-ACK）、`"A"`（ACK），并且 `packet 2` 的 `TCP.ack` 等于 `packet 1` 的 `seq + 1`，`packet 3` 的 `TCP.ack` 等于 `packet 2` 的 `seq + 1`。这体现了对**时序状态**与连接跟踪语义的最小一致性维护。

------

### 3. 智能体三：Input Pkt 逻辑审查员 (Constraint Critic)

**场景：** 审查员检查智能体二的输出。这里给出两种可能的情况。

**情况 A（打回重做）：** 如果智能体二产生幻觉，把 flags 写成了 "SYN"。

JSON

```
{
  "status": "FAIL",
  "feedback": "Error in packet_id 1: TCP.flags contains invalid string 'SYN'. Scapy requires a single character format. Please change to 'S'."
}
```

**情况 B（审核通过）：**

JSON

```
{
  "status": "PASS",
  "feedback": "Protocol stack matches parser paths. TCP flags and sequence numbers are logically continuous and syntactically correct."
}
```

**调度器动作：** 调度器看到 `PASS`，就把智能体二的 JSON 扔进 `convert_to_executable_format()` 变成二进制流。

> 工程落地备注（阶段性范围）：如果当前阶段仅实现“可读 JSON testcase（含 tx_host/topology_ref）”，则调度器可在此处直接落盘保存该 JSON，后续再接入格式转换与外置执行/预言机模块。

------

### 4. 智能体四：控制面规则生成师 (Control-Plane Entity Generator)

**场景：** 接收到 `control_plane_intent` 以及数据包的目标 IP，调用 `get_table` 后生成的匹配-动作表项（格式可以直接映射为 BMv2 CLI 命令）。

JSON

```
{
  "task_id": "T01_VALID_STATE_TRANSITION",
  "entities": [
    {
      "table_name": "ipv4_lpm",
      "match_type": "lpm",
      "match_keys": {
        "hdr.ipv4.dstAddr": ["10.0.0.5", 32]
      },
      "action_name": "ipv4_forward",
      "action_data": {
        "dstAddr": "00:00:00:00:00:01",
        "port": 1
      }
    },
    {
      "table_name": "ipv4_lpm",
      "match_type": "lpm",
      "match_keys": {
        "hdr.ipv4.dstAddr": ["8.8.8.8", 32]
      },
      "action_name": "ipv4_forward",
      "action_data": {
        "dstAddr": "00:00:00:00:00:02",
        "port": 2
      }
    }
  ]
}
```

**设计巧思：** 这个 JSON 结构极其清晰，转换脚本拿到后，一行代码就能把它拼成：`table_add ipv4_lpm ipv4_forward 10.0.0.5/32 => 00:00:00:00:00:01 1`。

------

### 5. 智能体五：实体规则合规审查员 (Entity Compliance Critic)

**场景：** 审查员对比 P4 编译后的源信息，检查上述 Entities。

**情况 A（打回重做）：** 如果智能体四忘记传 `dstAddr` 参数。

JSON

```
{
  "status": "FAIL",
  "feedback": "Action 'ipv4_forward' requires 2 parameters (dstAddr, port). Found 1 (port). Please provide the missing MAC address parameter."
}
```

**情况 B（审核通过）：**

JSON

```
{
  "status": "PASS",
  "feedback": "Table names, match types (lpm), and action parameter counts exactly match the P4 control block definitions."
}
```


## 五、验收标准（当前阶段工程落地：优先保证“触发时序状态/方向性策略”）

在仅实现“多智能体生成 input pkt（packet_sequence）并绑定拓扑发送者（tx_host）”的阶段，验收标准不应强求固定包数，而应以能否构造出**可触发时序状态机**、并体现**方向性策略**为核心。

以 `firewall` 为例（示意策略）：

- **允许：** internal 主机（例如 `h1`）作为 client 发起 TCP 连接到 external 主机（例如 `h3`）。
- **禁止：** external 主机（例如 `h3`）作为 client 主动向 internal 主机（例如 `h1`）发起 TCP 连接；`h3` 仅可作为 server 端回复。

当前阶段通过即视为通过：

1. **初始化加载与工具可用：** DOT/JSON/P4Info/Topology 已在阶段零加载进 ProgramContext，工具可实时查询并返回可追溯证据。
2. **输出 testcase JSON 可读且可复现：**
   - 输出包含 `topology_ref`；
   - `packet_sequence[]` 中每个 packet 都包含 `tx_host`（且该 host 必须存在于 topology hosts）。
3. **至少包含一个可触发时序状态的正例事务序列：**
   - 包含 internal→external 的 SYN 发起包；
   - 包含 external→internal 的回复包（如 SYN-ACK/ACK）；
   - （推荐）包含 internal 的 ACK 完成握手，使序列具有最小的时序闭环；
   - TCP flags/seq/ack 等字段在逻辑上自洽（由智能体三/规则审查或确定性校验函数保证）。
4. **（可选）包含一个方向性负例：**
   - external→internal 的 SYN 发起包作为 negative case（用于后续 P4CE/oracle 阶段验证其被拒绝/不通过状态校验的预期）。
