---
name: sbc_network_troubleshooting
description: 天基承载网（Space-Based Carrier Network）故障排查技能。从初始的故障现象出发，严格按照故障树逐步分析，对于每个破局点，在必要时调用相关工具进行排查，最终推断到结论节点，并且整合“破局点”、“定界节点”和“结论节点”形成结构化的排查结论。
---

# 天基承载网故障排查

## 1. 角色定位
你是一个用于天基承载网故障排查与辅助分析的技能。你的核心职责是：
1. 接收智能体拉起的故障排查请求，识别故障现象。
2. 严格按照故障树逐步分析，针对每个破局点，在必要时调用相关工具进行排查。
3. 最终推断到结论节点，并整合“破局点”、“定界节点”和“结论节点”形成结构化的排查结论。
**默认不要直接撰写长篇 Markdown 报告。**  
只有当用户明确提到“报告 / 故障排查报告 / markdown / md”时，你才在完成结构化分析后继续加载报告技能。

## 2. 基本概念知识
1. 无连接：指在天基承载网中，卫星之间的通信不依赖于传统的连接建立过程，而是通过无连接的方式进行数据传输。这种方式允许数据包在网络中独立传输，而不需要事先建立连接。
2. 联通子段：指在天基承载网中，卫星之间的通信链路形成的连续路径。一个联通子段可以包含多个卫星和链路，确保数据能够在这些卫星之间传输。
3. 落地卫星表：指记录卫星与地面站之间的通信关系的表格。该表格包含了卫星的标识、地面站的标识以及它们之间的通信状态。落地卫星表用于管理和监控卫星与地面站之间的通信连接，确保数据能够顺利传输到地面站。
4. 中断异常：指在天基承载网中，卫星之间的通信链路出现中断或异常，导致数据无法正常传输。这种异常可能由链路故障、卫星故障、地面站问题等多种因素引起。中断异常的识别对于故障排查和网络维护至关重要。
5. 破局点：指在故障排查过程中，关键的判断点或决策点。破局点的分析结果将直接影响后续的排查方向和结论。通过对破局点的深入分析，可以帮助确定故障的根本原因，从而制定有效的解决方案。
6. 定界节点：指在故障排查过程中，用于缩小排查范围的节点。定界节点的分析结果可以帮助确定故障可能存在的区域或环节，从而提高排查效率。通过对定界节点的分析，可以更好地定位问题所在，减少不必要的排查工作。
7. 结论节点：指在故障排查过程中，最终得出的分析结果或结论。结论节点的分析结果将直接反映故障的根本原因，为后续的解决方案提供依据。通过对结论节点的分析，可以明确故障的性质和影响范围，从而制定相应的修复措施。

## 3. 当前状态

### 人工选择工作流

当用户按日期查询无连接中断并要求排查时，采用以下固定流程：

1. 将日期规范化为当天完整查询窗口，先调用 `keep_alive_query` 全局查询。
2. 只将原始完整起止时间均一致的记录合并为一个候选事件。
3. 通过 LangGraph interrupt 返回候选事件并暂停；用户选择前不得进入故障树诊断节点。
4. 用户通过候选事件的稳定 `event_id` 选择后，以同一 Session/thread 恢复原图。
5. 选中事件的完整起止时间、卫星集合、类型和根节点证据注入状态，从 B 节点继续逐节点排查。
6. 前端展示和权限校验属于应用层；候选事件、暂停点及恢复位置由持久化 checkpointer 保存。

## 4. 背景与约束
### 模型辅助节点

- 数据库工具和故障树枚举判据仍是分支选择的首要依据；已有唯一合法 `outcome` 时，模型不得改写该结果。
- 当有效工具证据没有给出唯一一致的 `outcome` 时，允许进入受约束的 `llm_judge` 节点。模型只能从当前节点声明的 `outcomes` 中选择，并必须引用当前节点真实存在的证据ID；证据不足或输出不合法时，本分支以 `incomplete` 结束。
- 每次完整故障树诊断在 `build_result` 后调用一次 `llm_explain_result`，仅用于解释既有结论、实际分支、关键证据、排除项、置信度和下一步建议，不得改变结构化状态、结论、Judge或证据。
- 事件发现和等待人工选择阶段不调用模型；用户选定事件并完成本轮诊断后才调用。
- 每次模型调用必须记录模型入口、调用次数和token用量；模型生成内容与调用失败信息写入结构化JSON。模型等待期间前端保持“正在运行，请稍候...”状态。

### 已确认的观测口径
- 保活中断以原始完整起止时间分组：只有起止均一致的多星事件才合并，不使用查询窗口裁剪后的边界进行分组。
- 长中断包含短中断也不得合并；4.5 秒容差仅用于 PacketIn 匹配，不用于放宽中断事件分组。
- 同组内按照中断开始时的规划拓扑邻居优先扩展排查；此顺序只决定排查优先级，不是共同根因证据。
- 用户确认中断后调用 `connectionless_continuity_query` 查询连续性及分组，结果被截断时不得认为影响对象已完整列出。
- H17 使用 PacketIn 的 `occurred_bdt`，而非地面 `received_bdt`，与中断/恢复边界匹配，绝对时间差不超过 4.5 秒（含边界）。须同一链路的 LINK_DOWN 和 LINK_UP 分别对应，两条不同链路不能凑成匹配。
- Hello 周期为 1.5 秒，连续 3 个 Hello 丢失/收到分别触发 LINK_DOWN/LINK_UP；只有 PacketIn 事件记录时不得伪造逐包 Hello 证据。
- 星上路由观测为每半小时采样；不能把下一次查询到的路由状态回填为此前故障发生时刻的精确状态。
- 落地卫星表首次上注后3秒内没有收到直连星回执则每3秒重发，收到回执或离开规划弧段后停止；多次上注且无回执只能作为观测现象，不能单独判定馈电故障或其他根因。
- LAN/WAN 分接口收发证据本轮暂不模拟，不以一般报文日志冒充接口抓包。
- E1 的“末端节点”已确认：它是当前实际落地路由树中的叶子节点。例如实际路由为 `A星-B星-落地星`，且没有其他卫星的实际落地路径经过 A 星，则 A 星是末端节点。判断依据是选中的实际落地目标与 `observation_bdt` 之前最近一次星上路由表快照，不是物理/实时拓扑邻居数；目标星必须自身可达实际可用落地星，且没有其他源星经目标星落地。调用 `topology_query` 时指定 `check_terminal_node=true`、`observation_bdt` 和单颗目标星。
- 单星中断横跨多个规划落地星时归为长时间中断，只涉及一个规划落地星弧段时归为单圈次；固定落地星按中断开始时刻的规划落地星判断；两颗及以上卫星具有完全一致的中断起止时间即构成一批卫星。
- “多个联通分支”在实际落地路由树上判断；“有无落地路径”使用实际选中落地目标与最近一次星上路由快照。
- “邻居能落地”中的邻居取中断时实时拓扑的上、下、左、右邻星，1轨和6轨边界星只有三颗；有相关 PacketIn 时优先采用 PacketIn。
- 落地表状态以截止查询时刻的最新内容版本为准，任一上注尝试收到回执即视为该版本已响应。
- 馈电“全程正常”是指本批卫星完整保活中断区间内，相关规划馈电弧段均被正常实际弧段覆盖。
- 激光链路 as-of 判断同时核对双向链路最新事件与两端激光终端最近锁定遥测，两端都锁定才算正常。F7 有 PacketIn 时跳过激光检查并以 PacketIn 为先；无 PacketIn 时再查激光。
- F8 只检查星上路由表；H16 使用 `route_path_diagnosis` 选择一条实际落地路线并逐跳检查目的条目、可达性和下一跳。
- H2 无延时遥测时按“否”处理。I3 不伪造逐邻星扩散数据，直接进入 J4，并在结果中记录“邻居卫星扩散响应计数未获取”。
- F6 暂为结论节点“需根据抓包结果具体排查”，普通报文日志不得冒充 LAN/WAN 分接口抓包。

1. 你只能排查天基承载网的故障。
2. 你进行故障分析时，默认查询 **故障前后10分钟** 的数据。
   - 例如故障时刻为 `2008-08-08 08:00`
   - 则查询时间窗为 `2008-08-08 07:50` 到 `2008-08-08 08:10`
3. 若某一步缺少数据：
   - 先检查所调用的工具是否正确；
   - 检查工具调用的参数是否正确；
   - 若工具调用正确但仍无数据，则记录为数据缺失；
   - 该故障分支停止深入判断，并在结构化结果中明确标记 `status = "incomplete"`。
4. **本技能的目标产物是结构化分析结果，不是最终报告。**

## 5. 可用工具与使用边界
### 5.1 建议补充的领域工具（按故障树强相关）
1. `keep_alive_query`
   - 用途：识别中断异常、给出异常时间段与影响对象。
   - 触发：根节点 `识别异常` / `异常对象判断`。
   - 边界：只用于“是否异常 + 异常时间”，**不能单独作为根因结论**。
2. `topology_query`
   - 用途：判断是否存在落地路径、是否出现联通分支。
   - 触发：`E2 / E6 / F1 / F3 / F5` 相关判断。
   - 边界：必须带时间点（或短时间窗）+ 源/目的对象；不允许无时间全量扫。
3. `packetin_query`
   - 用途：核对中断/恢复时刻与转发事件是否对应。
   - 触发：`F1 / F7 / H17` 相关节点。
   - 边界：用于“证据校验”，不能越级替代拓扑与路由判断。
4. `feeder_link_query`
   - 用途：判断馈电链路连续性、落地卫星可用性。
   - 触发：`E3 / F5 / H8` 相关节点。
   - 边界：只判断馈电链路侧，不外推到星内承载网根因。
   - 联动要求：必须与 `landing_table_query` 联动，校验“落地卫星表中的目标卫星”是否真实建立馈电链路。
5. `SBC_telemetry_query`
   - 用途：激光锁定、译码状态、CPU/内存、关键载荷状态。
   - 触发：`F4 / I1 / H2 / H13` 相关节点。
   - 边界：需要明确参数名；若缺参先记录 `missing_data`，禁止凭经验补结论。
6. `packet_capture`
   - 用途：预留协议网关 LAN/WAN 分接口抓包能力。
   - 触发：当前故障树不调用。
   - 边界：本轮没有分接口抓包数据，调用时必须返回缺证据。
7. `route_table_query`
   - 用途：核查无连接路由表及路由条目有效性。
   - 触发：`F8` 分支。
   - 边界：只读查询，不改路由；结论必须关联时间点与目标卫星。
8. `laser_link_query`
   - 用途：查询激光链路锁定、上下线、质量状态。
   - 触发：`F4 / F7 / I1 / H13` 分支。
   - 边界：仅判定链路物理状态，不直接推断业务层根因。
9. `landing_table_query`
   - 用途：查询 `landing_table_update_observation` 的上注尝试与直连星收到即扩散观测，按 `update_id` 和 `attempt_no` 配对，并汇总尝试次数；回执不等于全网已生效。
   - 触发：`H2 / I3 / J4 / H6` 分支。
   - 边界：必须和拓扑或 packetin 交叉验证后再下结论。
   - 联动要求：查询到落地卫星表后，必须进一步调用 `feeder_link_query` 验证对应卫星在同时间窗是否建立馈电链路；若“表已生效但馈电未建链”，优先定界馈电侧/链路侧问题。
10. `alarm_event_query`
    - 用途：聚合网络告警、卫星历史告警和测量异常告警。
    - 触发：作为各分支的辅助线索，不直接驱动故障树跳转。
    - 边界：告警只能作为线索，不能单独作为最终结论。
11. `route_path_diagnosis`
    - 用途：选择目标星或其实时邻居的一条实际落地路线，并在同一路由快照上逐跳核对。
    - 触发：`H16`。
    - 边界：只读诊断；必须返回所用快照时间和首个异常跳，不把采样时刻回填为真实变化时刻。

### 5.2 通用工具边界（保留）
1. `write_file`
   - 仅用于写结构化结果与中间证据，不写长篇报告正文。
2. `load_skills`
   - 仅当用户明确要求“报告”时加载 `sbc_troubleshooting_report`。
3. `todo`
   - 多步骤任务必须持续更新，不允许只在开始或结束更新一次。
4. `read_file`
   - 仅用于读取已生成证据文件/配置快照，不用于替代领域查询工具。
5. `bash`
   - 默认禁用；仅当上述领域工具不可用且确有必要时，做最小只读辅助。
6. `web_search`
   - 仅用于补充公开背景知识，不能作为现场故障证据来源。

### 5.3 运行时落地提醒
- skill 中声明的领域工具必须在后端工具注册层真实接入后才可调用；若未接入，应在执行前显式报“工具不可用”，避免虚构调用结果。
- `feeder_link_query` 与 `landing_table_query` 在流程上视为“配对工具”：涉及落地卫星表生效判断时，必须执行“表状态 + 实际馈电建链”双证据校验，禁止只凭单一工具输出下结论。
- `route_table_query` 已查询 `onboard_routing_table_snapshot`，每半小时一条采样；不再使用 `station_selection_route` 冒充星上路由表。`observation_bdt` 可取该时刻之前最近样本，需同时检查样本年龄。
- 落地表的新回执证据只覆盖直连星收到即扩散。I3 不把直连星回执复制为其他星的回执，必须记录“邻居卫星扩散响应计数未获取”后进入 J4。

## 6. 排查流程（故障树）

### 6.1 机器可读故障树

以下 `yaml sbc-tree` 代码块是 SBC LangGraph 的**唯一故障树数据源**。操作人员修改故障树时只修改该代码块，
然后执行 `.venv/bin/python scripts/sync_sbc_fault_tree.py --write` 更新 Mermaid 视图。禁止手工修改自动生成的
Mermaid 区域。

```yaml sbc-tree
version: 1
root:
  node_id: A
  label: 通过保活时间统计识别XX时间内存在中断异常
  tool: keep_alive_query
  next: B
nodes:
  B:
    type: routing
    shape: decision
    label: 异常对象判断
    selector: pattern
    routes:
      single_pass: C1
      single_sat_long: C1
      fixed_landing_sat: C2
      fixed_sat_batch: C2
      multiple_sat_network: C2
    edge_labels:
      single_pass: 单颗星异常
      single_sat_long: 单颗星异常
      fixed_landing_sat: 多颗星异常
      fixed_sat_batch: 多颗星异常
      multiple_sat_network: 多颗星异常
  C1:
    type: routing
    shape: decision
    label: 初筛：总结规律
    selector: pattern
    routes:
      single_pass: D1
      single_sat_long: D2
    edge_labels:
      single_pass: 单圈次（单落地星）全程或短时间不通
      single_sat_long: 多圈次长时间（涉及多颗落地星）不通
  C2:
    type: routing
    shape: decision
    label: 初筛：总结规律
    selector: pattern
    routes:
      fixed_landing_sat: D3
      fixed_sat_batch: D4
      multiple_sat_network: D5
    edge_labels:
      fixed_landing_sat: 固定为某卫星落地时多颗星或所有卫星无法落地
      fixed_sat_batch: 固定为某一批卫星持续无法跨星落地
      multiple_sat_network: 不通落地星时存在不同的多颗卫星无法落地
  D1:
    type: routing
    label: 定性为节点或链路问题
    next: E1
  D2:
    type: routing
    label: 定性为节点问题
    next: E2
  D3:
    type: routing
    label: 定性为节点问题
    next: E3
  D4:
    type: breakpoint
    shape: decision
    label: 是否出现多个联通分支
    tools: [topology_query]
    outcomes:
      "yes": E4
      "no": E5
    edge_labels:
      "yes": 是
      "no": 否
  D5:
    type: routing
    label: 定性为网络问题
    next: E6
  E1:
    type: breakpoint
    shape: decision
    label: 破局点：是否为落地网络联通分支末端节点
    tools: [topology_query]
    outcomes:
      "yes": F1
      "no": F2
    edge_labels:
      "yes": 是
      "no": 否
  E2:
    type: breakpoint
    shape: decision
    label: 破局点：确认拓扑查询结果有无落地路径
    tools: [topology_query]
    outcomes:
      path_found: F3
      path_missing: F4
    edge_labels:
      path_found: 有
      path_missing: 无
  E3:
    type: breakpoint
    shape: decision
    label: 破局点：落地卫星表配置状态是否响应
    tools: [landing_table_query, feeder_link_query]
    required_evidence_groups:
      - [landing_table_query, feeder_link_query]
    outcomes:
      responded: F5
      not_responded: F6
    edge_labels:
      responded: 是
      not_responded: 否
  E4:
    type: routing
    label: 定性为链路问题
    next: F7
  E5:
    type: routing
    label: 定性为节点问题
    next: F8
  E6:
    type: breakpoint
    shape: decision
    label: 破局点：核查无法落地卫星在当时邻居能落地卫星的实时拓扑查询结果是否联通
    tools: [topology_query]
    outcomes:
      connected: F9
      not_connected: F10
    edge_labels:
      connected: 是
      not_connected: 否
  F1:
    type: breakpoint
    shape: decision
    label: 通过能落地的邻居卫星拓扑查询或Packetin判断星间网络是否联通、以及中断时间
    tools: [topology_query, packetin_query]
    outcomes:
      "yes": H1
      "no": H2
    edge_labels:
      "yes": 是
      "no": 否
  F2:
    type: boundary
    label: 定界承载网问题
    next: H3
  F3:
    type: boundary
    label: 定界承载网问题
    next: H4
  F4:
    type: breakpoint
    shape: decision
    label: 破局点：排查邻居链路激光锁定状态是否正常
    tools: [laser_link_query]
    outcomes:
      normal: H5
      abnormal: H6
    edge_labels:
      normal: 是
      abnormal: 否
  F5:
    type: breakpoint
    shape: decision
    label: 破局点：馈电链路是否全程正常
    tools: [landing_table_query, feeder_link_query]
    required_evidence_groups:
      - [landing_table_query, feeder_link_query]
    outcomes:
      normal: H7
      abnormal: H8
    edge_labels:
      normal: 是
      abnormal: 否
  F6:
    type: conclusion
    label: 需根据抓包结果具体排查
  F7:
    type: breakpoint
    shape: decision
    label: 破局点：通过中断时或恢复时的Packetin以及连接不同分支的激光链路锁定状态判断物理链路是否正常
    tools: [packetin_query, laser_link_query]
    outcomes:
      normal: H12
      abnormal: H13
    edge_labels:
      normal: 是
      abnormal: 否
  F8:
    type: breakpoint
    shape: decision
    label: 破局点：核查无法落地卫星的无连接路由状态（路由表、路由模式）是否正常
    tools: [route_table_query]
    outcomes:
      normal: H14
      abnormal: H15
    edge_labels:
      normal: 是
      abnormal: 否
  F9:
    type: boundary
    label: 定界承载网问题
    next: H16
  F10:
    type: boundary
    label: 定界链路问题
    next: H17
  H1:
    type: routing
    label: 定性为链路问题
    next: I1
  H2:
    type: breakpoint
    shape: decision
    label: 倒排：通过延时遥测判断落地卫星表是否收到（无延时遥测按否处理）
    tools: [SBC_telemetry_query]
    outcomes:
      received: I2
      not_received: I3
    edge_labels:
      received: 是
      not_received: 否
  H3:
    type: conclusion
    label: 落地卫星表未生效 / 源端未发出
  H4:
    type: conclusion
    label: 无连接路由异常 / 源端未发出 / 邻居卫星未转发
  H5:
    type: boundary
    label: 定界承载网问题
    next: I4
  H6:
    type: boundary
    label: 定界激光问题
    next: I5
  H7:
    type: boundary
    label: 定界承载网问题
    next: I6
  H8:
    type: boundary
    label: 定界馈电问题
    next: I7
  H12:
    type: boundary
    label: 定界承载网问题
    next: I11
  H13:
    type: boundary
    label: 定界激光问题
    next: I12
  H14:
    type: boundary
    label: 定界承载网问题
    next: I13
  H15:
    type: boundary
    label: 定界承载网问题
    next: I14
  H16:
    type: breakpoint
    label: 随后选择1条落地路线逐跳排查无连接路由表
    tools: [route_path_diagnosis]
    outcomes:
      checked: I15
    edge_labels:
      checked: ""
  H17:
    type: breakpoint
    shape: decision
    label: 破局点：无法落地和恢复落地的时间能否与Packetin消息完全对应
    tools: [packetin_query]
    outcomes:
      matched: I16
      not_matched: I17
    edge_labels:
      matched: 是
      not_matched: 否
  I1:
    type: breakpoint
    shape: decision
    label: 破局点：核查激光终端通信译码是否锁定
    tools: [SBC_telemetry_query, laser_link_query]
    outcomes:
      locked: J1
      unlocked: J2
    edge_labels:
      locked: 是
      unlocked: 否
  I2:
    type: boundary
    label: 定界承载网问题
    next: J3
  I3:
    type: breakpoint
    label: 记录邻居卫星扩散响应计数未获取并继续定界
    tools: [landing_table_query, feeder_link_query]
    required_evidence_groups:
      - [landing_table_query, feeder_link_query]
    outcomes:
      checked: J4
    edge_labels:
      checked: ""
  I4:
    type: conclusion
    label: 异常孤岛星等
  I5:
    type: conclusion
    label: 激光链路中断
  I6:
    type: conclusion
    label: 落地卫星表成功但未生效（扩散） / 落地卫星表内容有误未配置成功
  I7:
    type: conclusion
    label: 馈电链路中断、闪断、个别载波异常
  I11:
    type: conclusion
    label: 拓扑单通 / 星间转发异常等
  I12:
    type: conclusion
    label: 激光链路中断
  I13:
    type: conclusion
    label: 多颗星均出现星内异常（小概率）
  I14:
    type: conclusion
    label: 不同卫星具体的无连接路由状态异常
  I15:
    type: conclusion
    label: 某些卫星某些无连接路由表条目异常，或某些星间链路异常无法转发
  I16:
    type: conclusion
    label: 链路中断、路由无法自行恢复
  I17:
    type: boundary
    label: 定界承载网问题
    next: J5
  J1:
    type: boundary
    label: 定界承载网问题
    next: K1
  J2:
    type: boundary
    label: 定界激光问题
    next: K2
  J3:
    type: conclusion
    label: 落地卫星表未生效 / 源端未发出落地卫星表
  J4:
    type: boundary
    label: 任意结果，不管是否发出、是否收到响应均可定界为承载网问题
    next: K3
  J5:
    type: conclusion
    label: 针对无法说清的现象，将定界的异常剥离后再度分析
  K1:
    type: conclusion
    label: 星内承载网载荷异常（例如咬狗、复位、重启等）
  K2:
    type: conclusion
    label: 激光链路中断
  K3:
    type: conclusion
    label: 落地卫星表未扩散 / 落地卫星表扩散失败 / 落地卫星表未生效
```

### 6.2 自动生成的 Mermaid 视图

<!-- SBC_TREE_MERMAID_START -->

```mermaid
flowchart TD
    A["通过保活时间统计识别XX时间内存在中断异常"]
    B{"异常对象判断"}
    C1{"初筛：总结规律"}
    C2{"初筛：总结规律"}
    D1["定性为节点或链路问题"]
    D2["定性为节点问题"]
    D3["定性为节点问题"]
    D4{"是否出现多个联通分支"}
    D5["定性为网络问题"]
    E1{"破局点：是否为落地网络联通分支末端节点"}
    E2{"破局点：确认拓扑查询结果有无落地路径"}
    E3{"破局点：落地卫星表配置状态是否响应"}
    E4["定性为链路问题"]
    E5["定性为节点问题"]
    E6{"破局点：核查无法落地卫星在当时邻居能落地卫星的实时拓扑查询结果是否联通"}
    F1{"通过能落地的邻居卫星拓扑查询或Packetin判断星间网络是否联通、以及中断时间"}
    F2["定界承载网问题"]
    F3["定界承载网问题"]
    F4{"破局点：排查邻居链路激光锁定状态是否正常"}
    F5{"破局点：馈电链路是否全程正常"}
    F6["结论：需根据抓包结果具体排查"]
    F7{"破局点：通过中断时或恢复时的Packetin以及连接不同分支的激光链路锁定状态判断物理链路是否正常"}
    F8{"破局点：核查无法落地卫星的无连接路由状态（路由表、路由模式）是否正常"}
    F9["定界承载网问题"]
    F10["定界链路问题"]
    H1["定性为链路问题"]
    H2{"倒排：通过延时遥测判断落地卫星表是否收到（无延时遥测按否处理）"}
    H3["结论：落地卫星表未生效 / 源端未发出"]
    H4["结论：无连接路由异常 / 源端未发出 / 邻居卫星未转发"]
    H5["定界承载网问题"]
    H6["定界激光问题"]
    H7["定界承载网问题"]
    H8["定界馈电问题"]
    H12["定界承载网问题"]
    H13["定界激光问题"]
    H14["定界承载网问题"]
    H15["定界承载网问题"]
    H16["随后选择1条落地路线逐跳排查无连接路由表"]
    H17{"破局点：无法落地和恢复落地的时间能否与Packetin消息完全对应"}
    I1{"破局点：核查激光终端通信译码是否锁定"}
    I2["定界承载网问题"]
    I3["记录邻居卫星扩散响应计数未获取并继续定界"]
    I4["结论：异常孤岛星等"]
    I5["结论：激光链路中断"]
    I6["结论：落地卫星表成功但未生效（扩散） / 落地卫星表内容有误未配置成功"]
    I7["结论：馈电链路中断、闪断、个别载波异常"]
    I11["结论：拓扑单通 / 星间转发异常等"]
    I12["结论：激光链路中断"]
    I13["结论：多颗星均出现星内异常（小概率）"]
    I14["结论：不同卫星具体的无连接路由状态异常"]
    I15["结论：某些卫星某些无连接路由表条目异常，或某些星间链路异常无法转发"]
    I16["结论：链路中断、路由无法自行恢复"]
    I17["定界承载网问题"]
    J1["定界承载网问题"]
    J2["定界激光问题"]
    J3["结论：落地卫星表未生效 / 源端未发出落地卫星表"]
    J4["任意结果，不管是否发出、是否收到响应均可定界为承载网问题"]
    J5["结论：针对无法说清的现象，将定界的异常剥离后再度分析"]
    K1["结论：星内承载网载荷异常（例如咬狗、复位、重启等）"]
    K2["结论：激光链路中断"]
    K3["结论：落地卫星表未扩散 / 落地卫星表扩散失败 / 落地卫星表未生效"]

    A --> B
    B -->|单颗星异常| C1
    B -->|多颗星异常| C2
    C1 -->|单圈次（单落地星）全程或短时间不通| D1
    C1 -->|多圈次长时间（涉及多颗落地星）不通| D2
    C2 -->|固定为某卫星落地时多颗星或所有卫星无法落地| D3
    C2 -->|固定为某一批卫星持续无法跨星落地| D4
    C2 -->|不通落地星时存在不同的多颗卫星无法落地| D5
    D1 --> E1
    D2 --> E2
    D3 --> E3
    D4 -->|是| E4
    D4 -->|否| E5
    D5 --> E6
    E1 -->|是| F1
    E1 -->|否| F2
    E2 -->|有| F3
    E2 -->|无| F4
    E3 -->|是| F5
    E3 -->|否| F6
    E4 --> F7
    E5 --> F8
    E6 -->|是| F9
    E6 -->|否| F10
    F1 -->|是| H1
    F1 -->|否| H2
    F2 --> H3
    F3 --> H4
    F4 -->|是| H5
    F4 -->|否| H6
    F5 -->|是| H7
    F5 -->|否| H8
    F7 -->|是| H12
    F7 -->|否| H13
    F8 -->|是| H14
    F8 -->|否| H15
    F9 --> H16
    F10 --> H17
    H1 --> I1
    H2 -->|是| I2
    H2 -->|否| I3
    H5 --> I4
    H6 --> I5
    H7 --> I6
    H8 --> I7
    H12 --> I11
    H13 --> I12
    H14 --> I13
    H15 --> I14
    H16 --> I15
    H17 -->|是| I16
    H17 -->|否| I17
    I1 -->|是| J1
    I1 -->|否| J2
    I2 --> J3
    I3 --> J4
    I17 --> J5
    J1 --> K1
    J2 --> K2
    J4 --> K3
```

<!-- SBC_TREE_MERMAID_END -->

## 7. 故障树说明

- YAML 块是运行时唯一故障树数据源；Mermaid 仅用于展示并由同步脚本生成。
- 结论节点：`type: conclusion`，是最终排查结果。
- 定界节点：`type: boundary`，用于缩小排查范围。
- 破局点节点：`type: breakpoint`，必须声明允许调用的工具与有限枚举结果。
- 路由节点：`type: routing`，只执行确定性分类或直接流转，不调用工具。

## 8. 最终报告衔接

人工选择的中断事件完成故障树遍历后，必须执行以下收尾步骤：

1. 将选中事件、完整故障树遍历、工具查询参数、原始证据、定界节点、结论和缺失项保存为结构化JSON。
2. 加载 `sbc_troubleshooting_report` Skill。
3. 仅使用该JSON生成Markdown排查报告，不重新查询数据库，也不重新判断故障树分支。
4. 将诊断JSON和Markdown报告同时登记为当前Session工件。

结构化JSON必须保留每个遍历步骤的 `tree_node_id`、`node_type`、`decision`、`evidence_ids` 和 `next_node_id`。报告 Skill 依靠这些字段在完整故障树上高亮实际路径，并只把具备有效查询判据的 `breakpoint` 节点连续编号为 `Judge1/2/3...`；不得在诊断阶段预先拼接另一份简化故障树图。

结构化JSON还应保留 `llm_judgements`、`llm_explanation` 和 `llm_error`。这些字段只记录模型辅助过程；报告可以展示模型说明，但不得据此改写故障树分支和确定性结论。

即使排查因数据缺失而以 `incomplete` 结束，只要用户已经选择具体事件，也必须保存JSON并生成明确标注缺失项的报告。
