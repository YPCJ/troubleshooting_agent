import argparse
import json
import re
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JSON_PATH = PROJECT_ROOT / "skills" / "telemetry_query" / "output" / "fault_analysis_result.json"
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "skills" / "fault-analysis-report" / "templates" / "preliminary_report_template.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate fault analysis markdown report from structured JSON.")
    parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_PATH), help="Path to fault analysis JSON.")
    parser.add_argument(
        "--template",
        dest="template_path",
        default=str(DEFAULT_TEMPLATE_PATH),
        help="Path to markdown template with placeholders.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=str(PROJECT_ROOT),
        help="Directory to write generated report.",
    )
    return parser.parse_args()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(load_text(path))


def render_summary_table(fault_analyses: list[dict]) -> str:
    lines = ["| 故障类型 | 分析状态 | 结论 | 关键依据 |", "| --- | --- | --- | --- |"]
    for item in fault_analyses:
        lines.append(
            f"| {item.get('fault_type', '')} | {item.get('status', '')} | {item.get('conclusion', '')} | {item.get('summary', '')} |"
        )
    return "\n".join(lines)


def render_section(section_template: str, item: dict, index: int) -> str:
    result = section_template
    result = result.replace("{{section_index}}", str(index))
    result = result.replace("{{fault_type}}", item.get("fault_type", ""))
    result = result.replace("{{status}}", item.get("status", ""))
    result = result.replace("{{conclusion}}", item.get("conclusion", ""))

    key_evidence = "\n".join(f"- {value}" for value in item.get("key_evidence", []))
    decision_path = "\n".join(f"{i + 1}. {value}" for i, value in enumerate(item.get("decision_path", [])))
    missing_data = item.get("missing_data", [])
    missing_data_text = "\n".join(f"- {value}" for value in missing_data) if missing_data else "- 无"

    step_lines: list[str] = []
    for step in item.get("steps", []):
        window = step.get("query_time_range", {})
        step_lines.append(f"- **步骤 {step.get('step_no', '')}**")
        step_lines.append(f"  - 参数名：{step.get('parameter_name', '')}")
        step_lines.append(f"  - 查询时间窗：{window.get('start_time', '')} - {window.get('end_time', '')}")
        step_lines.append(f"  - 数据点数量：{step.get('data_points', '')}")
        step_lines.append(f"  - 最大值/最小值：{step.get('max_value', '')} / {step.get('min_value', '')}")
        step_lines.append(
            f"  - 比较结果：{step.get('comparison_result', '')}（阈值：{step.get('comparison_threshold', '')}）"
        )
        step_lines.append(f"  - 分支去向：{step.get('branch', '')} -> {step.get('next_action', '')}")

    result = result.replace("{{key_evidence}}", key_evidence)
    result = result.replace("{{decision_path}}", decision_path)
    result = result.replace("{{step_details}}", "\n".join(step_lines))
    result = result.replace("{{missing_data}}", missing_data_text)
    result = result.replace("{{fault_summary}}", item.get("summary", ""))
    return result


def parse_time_for_filename(raw_time: str) -> str:
    formats = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")
    for fmt in formats:
        try:
            return datetime.strptime(raw_time, fmt).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            continue
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def make_output_filename(metadata: dict) -> str:
    sat_id = str(metadata.get("satellite_id", "unknown")).strip() or "unknown"
    sat_token = re.sub(r"[^0-9A-Za-z_-]", "", sat_id) or "unknown"
    time_token = parse_time_for_filename(str(metadata.get("analysis_time", "")))
    return f"故障初步分析_卫星{sat_token}_{time_token}.md"


def render_report(template: str, data: dict) -> str:
    metadata = data.get("analysis_metadata", {})
    fault_analyses = data.get("fault_analyses", [])
    overall_summary = data.get("overall_summary", "")
    query_window = metadata.get("query_window", {})
    thresholds = metadata.get("thresholds", {})

    report_title = f"{metadata.get('satellite_id', '')}号卫星故障初步分析报告"
    query_window_text = f"{query_window.get('start_time', '')} ~ {query_window.get('end_time', '')}"
    thresholds_text = ", ".join(f"{k}={v}" for k, v in thresholds.items())
    summary_table = render_summary_table(fault_analyses)

    section_pattern = r"<!-- BEGIN_FAULT_SECTION_TEMPLATE -->(.*?)<!-- END_FAULT_SECTION_TEMPLATE -->"
    match = re.search(section_pattern, template, re.DOTALL)
    section_template = match.group(1).strip() if match else ""
    sections = [render_section(section_template, item, idx) for idx, item in enumerate(fault_analyses, start=1)]
    sections_text = "\n\n".join(sections)

    report = template
    report = report.replace("{{report_title}}", report_title)
    report = report.replace("{{analysis_time}}", str(metadata.get("analysis_time", "")))
    report = report.replace("{{fault_time}}", str(metadata.get("fault_time", "")))
    report = report.replace("{{satellite_id}}", str(metadata.get("satellite_id", "")))
    report = report.replace("{{query_window}}", query_window_text)
    report = report.replace("{{thresholds}}", thresholds_text)
    report = report.replace("{{summary_table}}", summary_table)
    report = report.replace("{{overall_summary}}", overall_summary)
    report = report.replace("{{fault_sections}}", sections_text)
    report = re.sub(section_pattern, "", report, flags=re.DOTALL)
    return report


def main() -> None:
    args = parse_args()
    json_path = Path(args.json_path).resolve()
    template_path = Path(args.template_path).resolve()
    output_dir = Path(args.output_dir).resolve()

    data = load_json(json_path)
    template = load_text(template_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_text = render_report(template, data)
    output_filename = make_output_filename(data.get("analysis_metadata", {}))
    output_path = output_dir / output_filename
    output_path.write_text(report_text, encoding="utf-8")
    print(f"Report generated successfully at {output_path}")


if __name__ == "__main__":
    main()
