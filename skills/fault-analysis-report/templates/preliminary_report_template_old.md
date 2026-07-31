# {{report_title}}

## 1. 基本信息

- **生成时间**: {{analysis_time}}
- **卫星编号**: {{satellite_id}}
- **故障发生时间**: {{fault_time}}
- **查询时间窗**: {{query_window}}
- **判断阈值**: {{thresholds}}

## 2. 结论汇总

{{summary_table}}

## 3. 详细分析过程

{{fault_sections}}

<!-- BEGIN_FAULT_SECTION_TEMPLATE -->
### 3.{{section_index}} {{fault_type}}

- **分析状态**: {{status}}
- **诊断结论**: {{conclusion}}

**一、 关键证据**
{{key_evidence}}

**二、 决策路径**
{{decision_path}}

**三、 详细步骤**
{{step_details}}

**四、 缺失数据**
{{missing_data}}

**五、 小结**
{{fault_summary}}
<!-- END_FAULT_SECTION_TEMPLATE -->

## 4. 综合总结

{{overall_summary}}
