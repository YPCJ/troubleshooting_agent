# -*- coding: utf-8 -*-
import json
import sys
import argparse
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

# set Chinese font with macOS-friendly fallbacks
plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'Noto Sans CJK SC']
plt.rcParams['axes.unicode_minus'] = False

# Global configuration
TIME_GAP_THRESHOLD_SEC = 1200  # Threshold for time gap in seconds (default 20 minutes)

def plot_chart(data_file):
    # read json data
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if isinstance(data, list):
        data = data[0]
    
    para_name = data['para_name']
    values = data['value']
    
    # parse time and values
    times = []
    point_values = []
    for item in values:
        t = datetime.strptime(item['time'], '%Y-%m-%d %H:%M:%S.%f')
        times.append(t)
        point_values.append(float(item['point_value']))
    
    # create chart
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # 1. Extract formatted time strings and calculate custom X coordinates with gaps
    time_labels = [t.strftime('%Y-%m-%d %H:%M:%S') for t in times]
    x_coords = [0]
    
    for i in range(1, len(times)):
        dt = (times[i] - times[i-1]).total_seconds()
        if dt > TIME_GAP_THRESHOLD_SEC:  # Gap larger than threshold
            x_coords.append(x_coords[-1] + 2) # Insert a smaller visual gap
        else:
            x_coords.append(x_coords[-1] + 1)
            
    # 2. Plot line chart segment by segment (solid for normal, dashed for gaps)
    # Draw all points
    ax.plot(x_coords, point_values, 'bo', markersize=4)
    
    added_label = False
    for i in range(len(times) - 1):
        x_pair = [x_coords[i], x_coords[i+1]]
        y_pair = [point_values[i], point_values[i+1]]
        dt = (times[i+1] - times[i]).total_seconds()
        
        if dt > TIME_GAP_THRESHOLD_SEC:
            # Dashed line for time gaps
            ax.plot(x_pair, y_pair, color='blue', linestyle='--', linewidth=1.5, alpha=0.5)
        else:
            # Solid line for continuous data
            label = para_name if not added_label else ""
            ax.plot(x_pair, y_pair, color='blue', linestyle='-', linewidth=1.5, label=label)
            added_label = True
            
    if not added_label:
        ax.plot([], [], color='blue', linestyle='-', label=para_name)
    
    # set title and labels
    sat_name = data.get('sat_name', '01号卫星')
    title_str = '{} {} 遥测数据趋势图'.format(sat_name, para_name)
    xlabel_str = '时间'
    ylabel_str = '数值'
    ax.set_title(title_str, fontsize=14, fontweight='bold')
    ax.set_xlabel(xlabel_str, fontsize=12)
    ax.set_ylabel(ylabel_str, fontsize=12)
    
    # 3. Format X axis ticks
    step = max(1, len(x_coords) // 15)
    tick_indices = list(range(0, len(x_coords), step))
    if len(x_coords) - 1 not in tick_indices:
        tick_indices.append(len(x_coords) - 1)
        
    ax.set_xticks([x_coords[i] for i in tick_indices])
    ax.set_xticklabels([time_labels[i] for i in tick_indices], rotation=45)
    
    # calculate average and variance
    avg_value = sum(point_values) / len(point_values)
    variance_value = sum((x - avg_value) ** 2 for x in point_values) / len(point_values)
    
    # add grid
    ax.grid(True, alpha=0.3)
    
    # add text label for average and variance
    text_str = '平均值: {:.4f}\n方差: {:.4f}'.format(avg_value, variance_value)
    
    # Get current handles and labels for the main legend
    handles, labels = ax.get_legend_handles_labels()
    
    # Create a dummy line for the statistics text
    dummy_line, = ax.plot([], [], ' ', label=text_str)
    
    handles.append(dummy_line)
    labels.append(text_str)
    
    # Create a single legend using loc='best' to avoid blocking the curve
    ax.legend(handles, labels, loc='best', fontsize=11)
    
    # auto adjust layout
    plt.tight_layout()
    
    # save image
    output_dir = Path(__file__).resolve().parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    current_time = datetime.now().strftime("%y%m%d_%H%M%S")
    output_path = output_dir / f"battery_plot_{current_time}.png"
    plt.savefig(output_path, dpi=150)
    print("Chart saved to: {}".format(output_path))
    
    # print statistics
    print("\nData statistics:")
    print("  Parameter: {}".format(para_name))
    print("  Data points: {}".format(len(point_values)))
    print("  Time range: {} ~ {}".format(times[0], times[-1]))
    print("  Max: {:.4f}".format(max(point_values)))
    print("  Min: {:.4f}".format(min(point_values)))
    print("  Average: {:.4f}".format(sum(point_values)/len(point_values)))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Satellite telemetry data plotting tool')
    parser.add_argument('--data', type=str, required=True, help='JSON data file path')
    args = parser.parse_args()
    plot_chart(args.data)