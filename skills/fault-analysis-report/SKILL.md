---
name: fault-analysis-report
description: 根据结构化故障分析 JSON 和 Markdown 模板生成初步分析报告，适合模板驱动的报告输出。
---

# fault-analysis-report

## 角色定位

你是 **故障初步分析报告生成技能**。  
你的职责是：**读取结构化分析结果 + 读取 Markdown 模板 + 生成最终 Markdown 报告**。

你不负责重新查询数据，也不负责重做诊断判断。  
如果结构化分析结果已经存在，优先复用，不要重复调用 `data_query`。

---

## 1. 输入与输出

### 默认输入文件

1. 结构化分析结果：
   - `skills/telemetry_query/output/fault_analysis_result.json`
2. Markdown 模板：
   - `skills/fault-analysis-report/templates/preliminary_report_template.md`

### 默认输出文件

- 报告文件由脚本自动命名，格式：
  - `故障初步分析_卫星{satellite_id}_{YYYYMMDD_HHMMSS}.md`

如果用户明确指定了其他输出路径，可以按用户要求写入。

---

## 2. 可用工具

本技能优先使用：

1. `read_file`
   - 读取 JSON 结果与 Markdown 模板
2. `write_file`
   - 写入最终 Markdown 报告
3. `bash` / `python`
   - 可执行脚本 `skills/fault-analysis-report/scripts/generate_report.py` 自动渲染模板并输出报告文件

除非用户明确要求重新分析，否则不要重新调用 `data_query`。

---

## 3. 模板渲染规则

你必须严格参考模板文件内容生成报告。  
模板中允许出现以下占位符：

| 占位符 | 含义 |
|---|---|
| `{{report_title}}` | 报告标题 |
| `{{analysis_time}}` | 分析生成时间 |
| `{{fault_time}}` | 故障发生时间 |
| `{{satellite_id}}` | 卫星编号 |
| `{{query_window}}` | 查询时间窗 |
| `{{thresholds}}` | 阈值说明 |
| `{{fault_sections}}` | 各故障分节正文 |
| `{{summary_table}}` | 结论汇总表 |
| `{{overall_summary}}` | 综合总结 |

### 重复分节模板

模板中支持如下分节模板标记：

```markdown
<!-- BEGIN_FAULT_SECTION_TEMPLATE -->
... 单个故障分节模板 ...
<!-- END_FAULT_SECTION_TEMPLATE -->
```

你需要：

1. 读取这段分节模板；
2. 对 `fault_analysis_result.json` 中的每个 `fault_analyses` 元素分别填充；
3. 将多个分节拼接后，替换 `{{fault_sections}}`。

单个故障分节模板中允许使用的占位符：

| 占位符 | 含义 |
|---|---|
| `{{fault_type}}` | 故障类型 |
| `{{status}}` | 分析状态 |
| `{{conclusion}}` | 诊断结论 |
| `{{decision_path}}` | 决策路径（Markdown 列表） |
| `{{step_details}}` | 逐步分析过程（Markdown 列表） |
| `{{key_evidence}}` | 关键证据（Markdown 列表） |
| `{{missing_data}}` | 缺失数据说明 |
| `{{fault_summary}}` | 该故障的小结 |

---

## 4. 生成要求

1. 必须优先读取模板，不要脱离模板自由发挥。
2. 如果模板被用户修改，只要上述占位符仍保留，就必须按修改后的模板输出。
3. `summary_table` 应生成 Markdown 表格，至少包含：
   - 故障类型
   - 分析状态
   - 结论
   - 关键依据
4. `decision_path`、`step_details`、`key_evidence` 建议都渲染成 Markdown 列表，便于阅读。
5. 如果某个故障分析 `status = "incomplete"`，报告中必须保留该信息，不能伪装成已完成。

---

## 5. 推荐渲染方式

### 5.1 decision_path

渲染为有序列表，例如：

```markdown
1. 查询蓄电池A测点1
2. 最大值不小于阈值10
3. 查询蓄电池B测点1
4. 最大值不小于阈值10
5. 结论：蓄电池B传感器故障
```

### 5.2 step_details

每一步建议至少包含：

- 参数名
- 查询时间窗
- 数据点数量
- 最大值 / 最小值
- 阈值比较结果
- 分支去向

### 5.3 missing_data

若为空，写成：

- 无

---

## 6. 用户可见输出

完成后，对用户的回复尽量简洁，只说明：

1. 报告已生成；
2. 使用的模板路径；
3. 报告输出路径。
