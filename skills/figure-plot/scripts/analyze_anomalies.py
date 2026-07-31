# -*- coding: utf-8 -*-
import json
import argparse
import numpy as np
from datetime import datetime
import sys

def analyze(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, list):
        data = data[0]

    para_name = data.get('para_name', 'Unknown Parameter')
    values = data.get('value', [])
    
    if not values:
        print("没有找到数据。")
        return

    times = [datetime.strptime(item['time'], '%Y-%m-%d %H:%M:%S.%f') for item in values]
    point_values = [float(item['point_value']) for item in values]

    # Basic stats
    mean_val = np.mean(point_values)
    std_val = np.std(point_values)
    max_val = np.max(point_values)
    min_val = np.min(point_values)

    print(f"=== {para_name} 基础统计 ===")
    print(f"数据点数: {len(point_values)}")
    print(f"时间范围: {times[0]} ~ {times[-1]}")
    print(f"均值: {mean_val:.4f}, 标准差: {std_val:.4f}")
    print(f"最大值: {max_val:.4f} (时间: {times[np.argmax(point_values)]})")
    print(f"最小值: {min_val:.4f} (时间: {times[np.argmin(point_values)]})")

    # 寻找偏离均值较大的点 (2*sigma 和 3*sigma)
    anomalies_2sigma = [(t, v) for t, v in zip(times, point_values) if abs(v - mean_val) > 2 * std_val]
    anomalies_3sigma = [(t, v) for t, v in zip(times, point_values) if abs(v - mean_val) > 3 * std_val]

    print(f"\n=== 阈值异常分析 ===")
    print(f"超过 2 倍标准差的数据点数: {len(anomalies_2sigma)}")
    print(f"超过 3 倍标准差的数据点数: {len(anomalies_3sigma)}")

    # 寻找突变点 (相邻两点差值较大)
    jumps = []
    for i in range(1, len(point_values)):
        diff = point_values[i] - point_values[i-1]
        time_diff = (times[i] - times[i-1]).total_seconds()
        # 如果时间间隔在1小时内，且数值变化超过 0.5 视为突变
        if time_diff > 0 and time_diff < 3600 and abs(diff) > 0.5:
            jumps.append((times[i-1], point_values[i-1], times[i], point_values[i], diff))

    print(f"\n=== 突变分析 (短时间内变化 > 0.5) ===")
    print(f"突变次数: {len(jumps)}")
    for j in jumps:
        print(f"时间段 {j[0]} 到 {j[2]}: 数值从 {j[1]:.4f} 变为 {j[3]:.4f} (变化量: {j[4]:.4f})")
        
    # 按天统计均值
    day_stats = {}
    for t, v in zip(times, point_values):
        day = t.strftime('%Y-%m-%d')
        if day not in day_stats:
            day_stats[day] = []
        day_stats[day].append(v)

    print(f"\n=== 按天统计 ===")
    for day, vals in day_stats.items():
        print(f"{day}: 均值 {np.mean(vals):.4f}, 最大值 {np.max(vals):.4f}, 最小值 {np.min(vals):.4f}, 数据点数 {len(vals)}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze anomalies in telemetry data')
    parser.add_argument('--data', type=str, required=True, help='Path to the JSON data file')
    args = parser.parse_args()
    analyze(args.data)