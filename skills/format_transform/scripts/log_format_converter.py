import pandas as pd
import os

# 标准化日志的column标题列表
standard_columns = [
    '星上时间', 'S/C相控阵天线测温点1', 'S/C相控阵天线测温点2', 'S/C相控阵天线测温点3',
    'S/C相控阵天线测温点4', 'S/C相控阵天线测温点5', 'S/C相控阵天线测温点6', 'S/C相控阵天线测温点7',
    'S/C相控阵天线测温点8', 'S/C相控阵天线测温点9', 'S/C相控阵天线测温点10', '蓄电池A测点1',
    # ... 省略其他标准列名
    '一线测温存储1', '一线测温存储2', '一线测温馈电高温', '一线测温馈电低温', '一线测温通用计算高温',
    '一线测温通用计算低温', '一线测温自主管理1', '一线测温自主管理2', '一线测温综合电子1',
    '一线测温路由主', '一线测温路由备', '一线测温安全1', '一线测温安全2', '一线测温导航1',
    '一线测温综合电子2', '一线测温配电上层', '一线测温配电下层', '一线测温电源SUN1',
    '一线测温电源SUN2', '一线测温电源BAT', '一线测温导航2', '一线测温综合电子3',
    '一线测温KA测控1', '一线测温KA测控2', '一线测温S测控1', '一线测温S测控2',
    '一线测温基带1', '一线测温基带2', '一线测温基带3', '一线测温基带4', '一线测温基带5',
    '一线测温基带6', '一线测温基带7', '一线测温基带8', '一线测温基带9', '一线测温基带10',
    '一线测温基带11', '一线测温基带12', '一线测温综合电子4', '一线测温40', '一线测温41',
    '一线测温42', '一线测温43', '一线测温44', '一线测温45', '一线测温46', '一线测温47',
    '一线测温48', '一线测温49', '一线测温50', '一线测温51', '一线测温52', '一线测温53',
    '一线测温54', '一线测温55', '一线测温56', '一线测温57', '一线测温58', '一线测温59',
    '一线测温60'
]

def convert_log_format(input_path, output_path):
    # 读取原始CSV文件
    df = pd.read_csv(input_path)

    # 获取原始文件的列标题
    original_columns = df.columns.tolist()

    # 初始化一个字典来存储需要映射的列
    column_mapping = {}

    # 找出需要映射或删除的列
    for col in original_columns:
        if col in standard_columns:
            # 如果列名匹配，则直接映射
            column_mapping[col] = col
        else:
            # 如果列名不匹配，则标记为'extra data'
            column_mapping[col] = 'extra data'

    # 创建一个新的DataFrame，仅包含标准化后的列
    new_df = pd.DataFrame(columns=standard_columns)

    # 填充新DataFrame的内容
    for col in standard_columns:
        if col in column_mapping.values():
            new_df[col] = df[next(key for key, value in column_mapping.items() if value == col)]
        else:
            # 如果标准化列不在原数据中，则填充为空值
            new_df[col] = None

    # 将额外的数据列添加到DataFrame中
    extra_data = {col: df[col] for col in df.columns if column_mapping[col] == 'extra data'}
    for col_name, data in extra_data.items():
        if 'extra data' not in new_df.columns:
            new_df['extra data'] = ''
        new_df['extra data'] += data.astype(str) + ' | '

    # 保存转换后的CSV文件
    new_df.to_csv(output_path, index=False)

# 定义输入和输出路径
input_files = ['PACK_12_0058_ss_20250824_100794625.csv', 'PACK_3_0056_ss_20251024_84017411.csv']
output_dir = 'converted_logs'
os.makedirs(output_dir, exist_ok=True)

# 对每个文件进行转换
for file in input_files:
    input_path = os.path.join('target', file)
    output_path = os.path.join(output_dir, f'converted_{file}')
    convert_log_format(input_path, output_path)
    print(f'Converted {file} to {output_path}')