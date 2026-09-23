---
name: sbc_troubleshooting_report
description: 排查报告生成。读取SBC LangGraph输出的结构化诊断JSON，绘制完整故障树并高亮实际分支，用Judge编号关联有效判据、关键证据、结论和缺失数据，生成Markdown排查报告。
---

# 排查报告生成

## 职责

本技能只负责将已经完成的SBC结构化诊断JSON转换为排查报告：

- 不重新查询数据库；
- 不改变LangGraph节点判断；
- 不补造JSON中不存在的证据；
- 必须保留不完整状态和缺失数据说明。

## 输入

输入JSON必须至少包含：

- `session_id`
- `selected_event`
- `status`
- `fault_window`
- `affected_objects`
- `fault_tree_branch`
- `evidence`
- `conclusions`

其中：

- `fault_tree_branch`记录实际走过的节点、节点类型、判断、下一节点；
- `evidence`记录节点调用的工具、查询参数、数据库结果和证据状态；
- `selected_event`记录用户实际选择的中断事件，不能用其他候选事件替代。
- `llm_judgements`、`llm_explanation`、`llm_error`为可选的模型辅助信息；它们只能解释既有诊断，不能覆盖故障树路径、Judge或结论。

## 输出

输出Markdown报告必须包含：

1. 事件概览；
2. 完整故障树与实际排查分支；
3. 按Judge编号关联的关键证据；
4. 其他证据与缺失证据；
5. 定界节点；
6. 初步结论；
7. 缺失数据与分析限制；
8. 数据来源说明。

如果输入包含 `llm_explanation`，在“初步结论”中增加“模型辅助分析”小节；如果仅包含 `llm_error`，明确标记模型说明未生成。无论哪种情况，都不得将模型文本当作新的数据库证据。

### 故障树绘制规则

- 必须直接绘制 `sbc_network_troubleshooting` Skill 中当前权威 `yaml sbc-tree` 的完整故障树，不能只输出实际路径表格，也不能另画一棵简化树。
- 使用 Mermaid `flowchart TD` 输出故障树。
- 本次未经过的节点和边保留默认样式；实际经过的节点和边使用蓝色高亮。
- 实际路径以诊断JSON中 `fault_tree_branch` 的原始顺序为准，不允许根据结论反推或补画路径。
- 图后附一行紧凑的实际节点序列，便于 Mermaid 不可用时阅读。

### Judge编号规则

- 只对本次实际经过的 `breakpoint` 节点编号。
- 该节点必须有关联证据，且用于本次判断的证据状态全部为 `valid`，节点判断不能是 `incomplete:*`。
- 按实际路径顺序连续编号为 `Judge1`、`Judge2`、`Judge3`……；不得使用故障树节点ID代替Judge编号。
- routing、boundary、conclusion、根节点以及仅有缺失/不可用证据的节点不编号。
- Judge节点在完整故障树中使用橙色高亮，并在节点正文中同时显示 `JudgeN` 和原节点名称。
- 同一节点的多条配对证据归属于同一个Judge，不得给每条工具证据各编一个Judge。

使用脚本：

```bash
.venv/bin/python skills/sbc_troubleshooting_report/scripts/generate_report.py \
  <诊断JSON路径> \
  --output <报告Markdown路径>
```

脚本输出路径后，必须将输入JSON和生成的Markdown同时作为Session工件返回。

## 证据表达规则

- “关键证据”章节必须按 `Judge1/2/3...` 分组；每组列出原故障树节点、判定结果、后续节点和该Judge关联的全部证据ID。
- 第3章“关键证据”和第4章“其他证据与缺失证据”中的每条证据都必须列出工具名称、所属故障树节点、查询时间窗、工具outcome和中文逻辑接入源名称。
- 逻辑接入源名称及主表映射以 [`data/仿真数据库说明.md`](../../data/仿真数据库说明.md) 第一节为准，格式为“中文逻辑接入源名称（`数据库表名`）”，不能只展示物理数据库文件路径或内部工具名。
- `topology_edge`、`keepalive_landing_candidate`、查询视图等不是18个逻辑接入源，必须另列为“辅助/增量数据源”。
- `landing_table_update_observation`、`onboard_routing_table_snapshot` 是仿真增量观测表，也必须另列为“辅助/增量数据源”，不得冒充原18个逻辑接入源。
- 一个工具实际联查多个逻辑接入源时全部列出；没有原18源直接对应时明确写“无原18个逻辑接入源直接对应”。
- 根节点证据、辅助证据、`missing_data`、`tool_unavailable` 等没有形成Judge的证据放入“其他证据与缺失证据”，不得伪装成Judge。
- 大体量原始行不全部复制到Markdown；报告只展示计数、关键字段及最多5条代表性记录。
- 完整原始查询结果以JSON工件为准。
- 如果证据状态不是`valid`，必须显式标记，不能写成确定性结论。
- 报告中的故障树路径必须按`fault_tree_branch`原顺序渲染。
