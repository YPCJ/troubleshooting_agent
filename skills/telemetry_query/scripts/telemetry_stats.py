# -*- coding: utf-8 -*-
"""
telemetry_stats.py - 01号卫星遥测数据统计分析脚本（telemetry_query 技能复用）

功能：
  1. 从 data_query 返回的 JSON 缓存文件（list[ {para_name, value:[{point_value, time}]} ]）
     加载遥测数据；
  2. 对每个参数做全量统计：数据点数、时间范围、均值、标准差、最大/最小值（含时间）；
  3. 按阈值（默认 max_value=10）输出"是否低于阈值"判定，便于配合蓄电池/天线故障诊断流程；
  4. 可选 --start/--end 参数，只统计 [start, end] 时窗内的数据（如故障前1h到故障后1h）；
  5. 输出低于阈值（异常低值/掉包）的点数及时段。

用法示例：
  python3 telemetry_stats.py \
      --data skills/figure-plot/assets/data_query_01_A_1__A_2__B_1_2025-10-01_00_00_2025-10-31_23_59_20260821144825.json \
      --threshold 10
  python3 telemetry_stats.py \
      --data <json> --threshold 10 \
      --start "2025-10-23 16:00" --end "2025-10-23 18:00"
"""
import json
import argparse
import numpy as np
from datetime import datetime
import sys


def parse_time(s):
    """兼容 '%Y-%m-%d %H:%M:%S.%f' 与 '%Y-%m-%d %H:%M:%S'"""
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError('无法解析时间: %s' % s)


def load_data(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 兼容单参数包装结构
        params = [data] if 'para_name' in data else []
        if not params:
            # 兼容 {"data": [...]}
            data = data.get('data', [])
            params = data if isinstance(data, list) else []
    elif isinstance(data, list):
        params = data
    else:
        params = []
    return params


def filter_window(records, start_dt, end_dt):
    out = []
    for r in records:
        t = parse_time(r['time'])
        if start_dt <= t <= end_dt:
            out.append(r)
    return out


def analyze_param(item, threshold, window=None):
    para_name = item.get('para_name', 'Unknown')
    records = item.get('value', [])
    if not records:
        print('  [%s] 无数据' % para_name)
        return None
    if window:
        start_dt, end_dt = parse_time(window[0]), parse_time(window[1])
        records = filter_window(records, start_dt, end_dt)
        print('  [%s] 时窗过滤后数据点数: %d' % (para_name, len(records)))
        if not records:
            print('  [%s] 时窗内无数据' % para_name)
            return None

    times = [parse_time(r['time']) for r in records]
    vals = np.array([float(r['point_value']) for r in records])

    mean_v = float(np.mean(vals))
    std_v = float(np.std(vals))
    max_v = float(np.max(vals))
    min_v = float(np.min(vals))
    i_max = int(np.argmax(vals))
    i_min = int(np.argmin(vals))

    below = [(t, v) for t, v in zip(times, vals) if v < threshold]

    print('=== %s 统计 ===' % para_name)
    print('  数据点数: %d' % len(vals))
    print('  时间范围: %s ~ %s' % (times[0], times[-1]))
    print('  均值: %.4f | 标准差: %.4f' % (mean_v, std_v))
    print('  最大值: %.4f (时间: %s)' % (max_v, times[i_max]))
    print('  最小值: %.4f (时间: %s)' % (min_v, times[i_min]))
    print('  阈值判定: max(%.4f) %s threshold(%s)  最小值低于阈值点数: %d'
          % (max_v, '>=' if max_v >= threshold else '<', threshold, len(below)))
    if below:
        print('  低于阈值时段(前3条):')
        for t, v in below[:3]:
            print('    %s : %.4f' % (t, v))
        print('  ...共 %d 条' % len(below))
    return {
        'para_name': para_name,
        'data_points': len(vals),
        'max_value': max_v,
        'min_value': min_v,
        'mean_value': mean_v,
        'std_value': std_v,
        'max_time': str(times[i_max]),
        'min_time': str(times[i_min]),
        'below_threshold_count': len(below),
        'threshold': threshold,
    }


def main():
    parser = argparse.ArgumentParser(description='01号卫星遥测数据统计分析')
    parser.add_argument('--data', required=True, help='data_query 缓存 JSON 文件路径')
    parser.add_argument('--threshold', type=float, default=10.0, help='判定阈值（默认10）')
    parser.add_argument('--start', default=None, help='时窗起始, 例如 "2025-10-23 16:00"')
    parser.add_argument('--end', default=None, help='时窗结束, 例如 "2025-10-23 18:00"')
    args = parser.parse_args()
    window = None
    if args.start and args.end:
        window = (args.start, args.end)
    elif args.start or args.end:
        parser.error('--start 与 --end 必须同时提供')
    else:
        window = None

    params = load_data(args.data)
    if not params:
        print('未找到可解析的参数数据。')
        sys.exit(1)

    print('读取文件: %s' % args.data)
    results = []
    for item in params:
        r = analyze_param(item, args.threshold, window)
        if r:
            results.append(r)
        print()

    # 汇总
    print('====== 汇总 ======')
    for r in results:
        verdict = '正常(>=阈值)' if r['max_value'] >= r['threshold'] else '异常(<阈值)'
        print('  %s: max=%.4f min=%.4f 点数=%d -> %s'
              % (r['para_name'], r['max_value'], r['min_value'], r['data_points'], verdict))
    print('全部完成。')


if __name__ == '__main__':
    main()