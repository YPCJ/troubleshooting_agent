#!/usr/bin/env python3
"""生成故障初步分析报告"""
import json
from datetime import datetime

# 读取结构化分析结果
with open('skills/telemetry_query/output/fault_analysis_result.json', 'r') as f:
    result = json.load(f)

# 读取模板
with open('skills/fault-analysis-report/templates/preliminary_report_template.md', 'r') as f:
    template = f.read()

meta = result['analysis_metadata']
analysis_time = meta['analysis_time']
sat_id = meta['satellite_id']
fault_time = meta['fault_time']
start = meta['query_window']['start_time']
end = meta['query_window']['end_time']
thresholds = meta['thresholds']

# 提取分节模板
section_start = template.find('<!-- BEGIN_FAULT_SECTION_TEMPLATE -->')
section_end = template.find('<!-- END_FAULT_SECTION_TEMPLATE -->')
section_template = template[section_start + len('<!-- BEGIN_FAULT_SECTION_TEMPLATE -->'):section_end].strip()

# 生成故障分节
fault_sections = []
for i, fa in enumerate(result['fault_analyses'], 1):
    sec = section_template
    sec = sec.replace('{{section_index}}', str(i))
    sec = sec.replace('{{fault_type}}', fa['fault_type'])
    sec = sec.replace('{{status}}', fa['status'])
    sec = sec.replace('{{conclusion}}', fa['conclusion'])
    # decision_path
    dp = '\n'.join([f"{j}. {step}" for j, step in enumerate(fa['decision_path'], 1)])
    sec = sec.replace('{{decision_path}}', dp)
    # step_details
    sd_lines = []
    for step in fa['steps']:
        sd_lines.append(f"**步骤{step['step_no']}：查询 `{step['parameter_name']}`**")
        sd_lines.append(f"- 查询时间窗：{step['query_time_range']['start_time']} ~ {step['query_time_range']['end_time']}")
        sd_lines.append(f"- 数据点数：{step['data_points']}")
        sd_lines.append(f"- 最大值：{step['max_value']}，最小值：{step['min_value']}")
        sd_lines.append(f"- 阈值比较：{step['comparison_result']}（阈值 = {step['comparison_threshold']}）")
        sd_lines.append(f"- 分支判断：{step['branch']} → {step['next_action']}")
        sd_lines.append("")
    sec = sec.replace('{{step_details}}', '\n'.join(sd_lines))
    # key_evidence
    ke = '\n'.join([f"- {ev}" for ev in fa['key_evidence']])
    sec = sec.replace('{{key_evidence}}', ke)
    # missing_data
    md = '\n'.join([f"- {d}" for d in fa['missing_data']]) if fa['missing_data'] else '- 无'
    sec = sec.replace('{{missing_data}}', md)
    sec = sec.replace('{{fault_summary}}', fa['summary'])
    fault_sections.append(sec)

# 移除模板标记，保留主模板（只移除section template定义，不替换为{{fault_sections}}）
main_template = template[:section_start] + template[section_end + len('<!-- END_FAULT_SECTION_TEMPLATE -->'):]

# 生成汇总表
summary_rows = []
for fa in result['fault_analyses']:
    evidence_brief = fa['key_evidence'][0][:60] + '...' if fa['key_evidence'] else '无'
    summary_rows.append(f"| {fa['fault_type']} | {fa['status']} | {fa['conclusion']} | {evidence_brief} |")

summary_table = f"""| 故障类型 | 分析状态 | 结论 | 关键依据 |
|----------|----------|------|----------|
{chr(10).join(summary_rows)}"""

# 填充主模板
report = main_template
report = report.replace('{{report_title}}', f'01号卫星能源系统故障初步分析报告')
report = report.replace('{{satellite_id}}', sat_id)
report = report.replace('{{fault_time}}', fault_time)
report = report.replace('{{analysis_time}}', analysis_time)
report = report.replace('{{query_window}}', f'{start} ~ {end}')
report = report.replace('{{thresholds}}', f'max_value = {thresholds["max_value"]}, max_power = {thresholds["max_power"]}')
report = report.replace('{{fault_sections}}', '\n\n'.join(fault_sections))
report = report.replace('{{summary_table}}', summary_table)
report = report.replace('{{overall_summary}}', result['overall_summary'])

# 输出文件名
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
out_path = f'故障初步分析_卫星{sat_id}_{ts}.md'
with open(out_path, 'w') as f:
    f.write(report)

print(f'报告已生成: {out_path}')