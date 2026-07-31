import pandas as pd
import matplotlib.pyplot as plt
data = pd.read_csv('/Users/ypcj/GIT/fault_assistant_AI/battery_A_point1_data_2025-10-28_1500_to_1800.csv')
data['time'] = pd.to_datetime(data['time'])
plt.figure(figsize=(10, 6))
plt.plot(data['time'], data['point_value'], marker='o', linestyle='-')
plt.title('蓄电池A测点1数据')
plt.xlabel('时间')
plt.ylabel('测点值')
plt.gcf().autofmt_xdate()
plt.savefig('/Users/ypcj/GIT/fault_assistant_AI/battery_A_point1_chart.png')