# {{report_title}}

**故障卫星：** {{satellite_id}}  
**故障时间：** {{fault_time}}  
**分析时间：** {{analysis_time}}  
**分析范围：** {{query_window}}（故障前后各1小时）  
**阈值配置：** {{thresholds}}

---

## 一、分项故障排查详情

{{fault_sections}}

---

## 二、结论汇总

{{summary_table}}

---

## 三、总体结论

{{overall_summary}}

<!-- BEGIN_FAULT_SECTION_TEMPLATE -->
### {{section_index}}. {{fault_type}}

**分析状态：** {{status}}  
**故障结论：** {{conclusion}}

#### 决策路径
{{decision_path}}

#### 故障排查过程及判断依据
{{step_details}}

#### 关键证据
{{key_evidence}}

#### 缺失数据
{{missing_data}}

#### 小结
{{fault_summary}}
<!-- END_FAULT_SECTION_TEMPLATE -->
