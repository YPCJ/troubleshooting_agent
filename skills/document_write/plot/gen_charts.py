# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

output_dir = Path(__file__).resolve().parent

# ===== 图1: 各卫星7天预警总数对比 =====
satellites = ['试验卫星01星', '试验卫星02星', '试验卫星04星']
total_warnings = [77, 735, 9]
colors = ['#FF6B6B', '#4ECDC4', '#45B7D1']

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(satellites, total_warnings, color=colors, width=0.5, edgecolor='black', linewidth=1.5)

for bar, val in zip(bars, total_warnings):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10, str(val),
            ha='center', va='bottom', fontsize=14, fontweight='bold')

ax.set_ylabel('预警总数（条）', fontsize=13)
ax.set_title('各卫星7天预警总数对比', fontsize=15, fontweight='bold', pad=15)
ax.set_ylim(0, max(total_warnings) * 1.15)
ax.grid(axis='y', alpha=0.3, linestyle='--')

plt.tight_layout()
plt.savefig(output_dir / "fig1_sat_warnings.png", dpi=150, bbox_inches='tight')
plt.close()
print("[OK] 图1已生成")

# ===== 图2: 各卫星预警等级分布对比 =====
# 统计各卫星不同预警等级的参数个数
# 01星: 1级=4个参数(S/C相控阵天线测温点1, 太阳翼A轴SADA测温点2, 太阳翼B轴SADA测温点4, BPO2-VCC0V8_FT1电压), 3级=6个参数
# 02星: 4级=1个, 5级=3个, 6级=10个
# 04星: 5级=1个

levels = ['1级', '2级', '3级', '4级', '5级', '6级']
sat01_levels = [4, 0, 6, 0, 0, 0]
sat02_levels = [0, 0, 0, 1, 3, 10]
sat04_levels = [0, 0, 0, 0, 1, 0]

x = np.arange(len(levels))
width = 0.25

fig, ax = plt.subplots(figsize=(12, 6))
bars1 = ax.bar(x - width, sat01_levels, width, label='试验卫星01星', color='#FF6B6B', edgecolor='black', linewidth=1)
bars2 = ax.bar(x, sat02_levels, width, label='试验卫星02星', color='#4ECDC4', edgecolor='black', linewidth=1)
bars3 = ax.bar(x + width, sat04_levels, width, label='试验卫星04星', color='#45B7D1', edgecolor='black', linewidth=1)

for bars in [bars1, bars2, bars3]:
    for bar in bars:
        if bar.get_height() > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3, str(int(bar.get_height())),
                    ha='center', va='bottom', fontsize=10, fontweight='bold')

ax.set_xlabel('预警等级', fontsize=13)
ax.set_ylabel('参数个数', fontsize=13)
ax.set_title('各卫星预警等级分布对比', fontsize=15, fontweight='bold', pad=15)
ax.set_xticks(x)
ax.set_xticklabels(levels, fontsize=11)
ax.legend(fontsize=11)
ax.grid(axis='y', alpha=0.3, linestyle='--')

plt.tight_layout()
plt.savefig(output_dir / "fig2_level_distribution.png", dpi=150, bbox_inches='tight')
plt.close()
print("[OK] 图2已生成")

# ===== 图3: 试验卫星01星各预警参数分布 =====
params_01 = ['BPO2-VCC0V8_FT1\n电压', 'BPO2-FPGA1_NET\nAurora Ch up', 'BPO3-EDAC\n写入Flash ID',
             'BPO3-FPGA2_IQ\nPCIe link up', 'BPO3-FPGA2_NET\nPCIe linkup',
             'BPO3-FPGA2_NET\nAurora Cha up', 'BPO3-FPGA2_IQ\nAurora SI',
             'S/C相控阵\n天线测温点1', '太阳翼A轴\nSADA测温点2', '太阳翼B轴\nSADA测温点4']
values_01 = [10, 8, 8, 16, 8, 8, 8, 11, 0, 0]
colors_01 = ['#FF4444', '#FF8C00', '#FF8C00', '#FF8C00', '#FF8C00', '#FF8C00', '#FF8C00', '#FF4444', '#FF4444', '#FF4444']

fig, ax = plt.subplots(figsize=(14, 6))
bars = ax.barh(params_01, values_01, color=colors_01, edgecolor='black', linewidth=1.2)

for bar, val in zip(bars, values_01):
    if val > 0:
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, str(val),
                ha='left', va='center', fontsize=11, fontweight='bold')

ax.set_xlabel('7天预警事件数（条）', fontsize=13)
ax.set_title('试验卫星01星各预警参数分布', fontsize=15, fontweight='bold', pad=15)
ax.set_xlim(0, max(values_01) * 1.3)
ax.grid(axis='x', alpha=0.3, linestyle='--')

plt.tight_layout()
plt.savefig(output_dir / "fig3_sat01_params.png", dpi=150, bbox_inches='tight')
plt.close()
print("[OK] 图3已生成")

# ===== 图4: 试验卫星02星各预警参数分布 =====
params_02 = ['12V主份电源\n电压', '28V备份电源\n电压', '28V主份电源\n电压', '5V主份电源\n电压',
             '12V备份电源\n电压', '-12V备份电源\n电压', '母线电压\n遥测1', '28V指令电源\n电压',
             '母线电压\n遥测2', '-12V主份电源\n电压', 'X02电源\n电压关联', '接收波束一\n俯仰角',
             '发射波束一\n俯仰角', '5V备份电源\n电压']
values_02 = [110, 339, 40, 11, 11, 11, 75, 11, 60, 12, 6, 25, 23, 1]
# 根据预警等级着色：4级=红, 5级=橙, 6级=蓝
colors_02 = []
for p in params_02:
    if 'X02' in p:
        colors_02.append('#FF8C00')  # 4级 橙色
    elif '指令' in p or '俯仰' in p:
        colors_02.append('#90EE90')  # 5级 浅绿
    else:
        colors_02.append('#4ECDC4')  # 6级 青色

fig, ax = plt.subplots(figsize=(14, 8))
bars = ax.barh(params_02, values_02, color=colors_02, edgecolor='black', linewidth=1.2)

for bar, val in zip(bars, values_02):
    if val > 0:
        ax.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2, str(val),
                ha='left', va='center', fontsize=10, fontweight='bold')

ax.set_xlabel('7天预警事件数（条）', fontsize=13)
ax.set_title('试验卫星02星各预警参数分布', fontsize=15, fontweight='bold', pad=15)
ax.set_xlim(0, max(values_02) * 1.15)
ax.grid(axis='x', alpha=0.3, linestyle='--')

plt.tight_layout()
plt.savefig(output_dir / "fig4_sat02_params.png", dpi=150, bbox_inches='tight')
plt.close()
print("[OK] 图4已生成")

print("[ALL_OK] 所有图表生成完毕")