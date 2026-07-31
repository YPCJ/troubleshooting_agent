<!--
可编辑模板。
保留主要占位符后，后续生成的报告会自动跟随模板变化。

支持的顶层占位符：
{{report_title}}
{{analysis_time}}
{{fault_time}}
{{satellite_id}}
{{query_window}}
{{thresholds}}
{{fault_sections}}
{{summary_table}}
{{overall_summary}}
-->

# {{report_title}}

**分析时间：** {{analysis_time}}  
**故障时间：** {{fault_time}}  
**故障卫星：** {{satellite_id}}  
**查询时间窗：** {{query_window}}  
**阈值配置：** {{thresholds}}

---

{{fault_sections}}

---

## 结论汇总

{{summary_table}}

### 综合说明

{{overall_summary}}

<!-- BEGIN_FAULT_SECTION_TEMPLATE -->
## {{fault_type}}

### 分析状态
{{status}}

### 故障排查结果
**结论：{{conclusion}}**

### 决策路径
{{decision_path}}

### 故障排查过程及判断依据
{{step_details}}

### 关键证据
{{key_evidence}}

### 缺失数据
{{missing_data}}

### 小结
{{fault_summary}}
<!-- END_FAULT_SECTION_TEMPLATE -->
