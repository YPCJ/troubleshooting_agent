# -*- coding: utf-8 -*-
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# 数据准备
times_str = [
    "2025-10-24 17:19:36", "2025-10-24 17:20:08", "2025-10-24 17:20:40", "2025-10-24 17:21:12",
    "2025-10-24 17:21:44", "2025-10-24 17:22:16", "2025-10-24 17:22:48", "2025-10-24 17:23:20",
    "2025-10-24 17:23:52", "2025-10-24 17:24:24", "2025-10-24 17:24:56", "2025-10-24 17:25:28",
    "2025-10-24 17:26:00", "2025-10-24 17:26:32", "2025-10-24 17:27:04", "2025-10-24 17:27:36",
    "2025-10-24 17:28:08", "2025-10-24 17:28:40", "2025-10-24 17:29:12", "2025-10-24 17:29:44",
    "2025-10-24 17:30:16", "2025-10-24 17:30:48",
    "2025-10-24 18:52:25", "2025-10-24 18:52:57", "2025-10-24 18:53:29", "2025-10-24 18:54:01",
    "2025-10-24 18:54:33", "2025-10-24 18:55:05", "2025-10-24 18:55:37", "2025-10-24 18:56:09",
    "2025-10-24 18:56:41", "2025-10-24 18:57:13", "2025-10-24 18:57:45", "2025-10-24 18:58:17",
    "2025-10-24 18:58:49", "2025-10-24 18:59:21", "2025-10-24 18:59:53"
]
times = [datetime.strptime(t, "%Y-%m-%d %H:%M:%S") for t in times_str]

# 星敏感器A
data_A = [-9.070995, -9.244767, -9.384623, -9.490057, -9.665562, -9.806657, -9.936319, -10.090133,
          -10.232527, -10.459115, -10.566525, -10.758506, -10.988064, -10.999664, -11.096502, -11.242168,
          -11.474569, -11.584001, -11.719929, -11.807067, -11.80339, -12.077229,
          -8.426086, -8.417072, -8.600182, -8.725796, -8.944209, -9.002538, -9.141489, -9.280835,
          -9.327372, -9.595617, -9.701304, -9.842291, -9.983705, -10.161403, -10.268313]

# 星敏感器B
data_B = [-9.210281, -9.571732, -9.853784, -10.101949, -10.28009, -10.518659, -10.843175, -10.999664,
          -11.242168, -11.523527, -11.731354, -12.02764, -12.165267, -12.276192, -12.476142, -12.576493,
          -12.817316, -12.929743, -13.071002, -13.161839, -13.104331, -13.337427,
          5.22577, 5.09369, 4.893552, 4.710473, 4.527176, 4.309819, 4.189581, 4.029226,
          3.868823, 3.684846, 3.547851, 3.347115, 3.226621, 3.026799, 2.889601]

# 星敏感器C
data_C = [-4.705682, -4.907779, -5.037368, -5.267071, -5.427623, -5.601806, -5.807184, -5.951585,
          -6.215195, -6.334572, -6.479939, -6.612747, -6.822049, -6.968367, -7.102288, -7.281339,
          -7.493444, -7.641167, -7.809542, -7.978616, -8.073521, -8.276656,
          -4.619713, -4.745669, -4.831659, -5.12027, -5.236899, -5.423515, -5.597422, -5.684549,
          -5.902885, -6.109078, -6.253802, -6.385912, -6.51831, -6.631554, -6.911115]

# 创建图表 - 使用英文标签避免字体问题
fig, ax = plt.subplots(figsize=(14, 7))

# 绘制三个星敏感器，星敏感器B加粗突出显示
ax.plot(times, data_A, 'b-', linewidth=1.5, alpha=0.8, label='Star Sensor A')
ax.plot(times, data_B, 'r-', linewidth=3.5, alpha=1.0, label='Star Sensor B (FAULT)')
ax.plot(times, data_C, 'g-', linewidth=1.5, alpha=0.8, label='Star Sensor C')

# 标注故障点 - 数据断开区域
fault_start = datetime.strptime("2025-10-24 17:30:48", "%Y-%m-%d %H:%M:%S")
fault_end = datetime.strptime("2025-10-24 18:52:25", "%Y-%m-%d %H:%M:%S")
ax.axvspan(fault_start, fault_end, color='gray', alpha=0.15, label='Fault Period (~18:00)')

# 添加注释标注星敏感器B的数值反转
ax.annotate('Value jumps from -13.34 to +5.23\nPolarity REVERSED! Amplitude=18.57',
            xy=(times[22], data_B[22]), xytext=(times[15], data_B[22]+6),
            arrowprops=dict(arrowstyle='->', color='red', lw=2),
            fontsize=11, color='red', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

# 设置坐标轴
ax.set_xlabel('Time', fontsize=12)
ax.set_ylabel('Sensor Value', fontsize=12)
ax.set_title('Satellite 01 - Three Star Sensors Telemetry (2025-10-24 17:19~18:59)', fontsize=14, fontweight='bold')
ax.legend(loc='best', fontsize=11)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
plt.xticks(rotation=45)

plt.tight_layout()
output_dir = Path(__file__).resolve().parent / "plot"
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / "star_sensors_combined.png"
plt.savefig(output_path, dpi=150)
print(f"Combined chart saved: {output_path}")
plt.close()