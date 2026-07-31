#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卫星遥测参数日志格式转换脚本
将PACK格式的目标日志文件转换为标准化格式

标准化格式列（145列）：
    星上时间, S/C相控阵天线测温点1, ..., 一线测温60

目标文件格式列（160列）：
    解析时间, 接收时间, 地面时间, 星上时间, 链路, ..., 包长, 
    S/C相控阵天线测温点1, ..., 一线测温60

转换逻辑：
    1. 保留"星上时间"列（第4列，索引3）
    2. 保留所有遥测参数列（从第17列到第160列，索引16到159，共144列）
    3. 删除前16列中的其余15个链路层字段
    4. 将时间格式从"yyyy-MM-dd hh:mm:ss.fff"统一转换为"yyyy-MM-dd hh:mm:ss.f"
"""

import pandas as pd
import argparse
import os
import sys
import warnings
warnings.filterwarnings('ignore')


def convert_log(input_file, output_file=None, encoding='utf-8'):
    """将目标日志文件转换为标准化格式"""
    
    print(f"[INFO] 读取目标文件: {input_file}")
    print(f"[INFO] 使用编码: {encoding}")
    
    # 1. 读取目标CSV文件
    try:
        df = pd.read_csv(input_file, encoding=encoding)
    except Exception as e:
        print(f"[ERROR] 读取文件失败: {e}")
        for enc in ['gbk', 'gb18030', 'gb2312', 'latin1']:
            try:
                df = pd.read_csv(input_file, encoding=enc)
                encoding = enc
                print(f"[INFO] 使用编码 {enc} 成功读取")
                break
            except:
                continue
        else:
            print("[ERROR] 无法读取文件，请检查编码")
            sys.exit(1)
    
    print(f"[INFO] 文件读取成功，共 {len(df)} 行，{len(df.columns)} 列")
    
    # 2. 获取目标文件的列名
    target_columns = list(df.columns)
    #print(f"[INFO] 目标文件列数: {len(target_columns)}")
    #print(f"[INFO] 前5列: {target_columns[:5]}")
    #print(f"[INFO] 最后3列: {target_columns[-3:]}")
    
    # 3. 确认标准格式所需的列
    # 星上时间在索引3，遥测参数从索引16开始到最后（共144个参数）
    star_time_col = target_columns[3]  # '星上时间'
    telemetry_cols = target_columns[16:]  # 144个遥测参数列
    
    # 验证遥测参数列数是否为144
    if len(telemetry_cols) != 144:
        print(f"[WARN] 遥测参数列数预期为144，实际为 {len(telemetry_cols)}")
    
    standard_columns = [star_time_col] + telemetry_cols
    
    print(f"[INFO] 标准化格式列数: {len(standard_columns)} (预期: 145)")
    print(f"[INFO] 第一列: {standard_columns[0]}")
    print(f"[INFO] 前3个遥测参数: {standard_columns[1:4]}")
    print(f"[INFO] 最后3列: {standard_columns[-3:]}")
    
    # 4. 提取标准化数据
    std_df = df[standard_columns].copy()
    
    # 5. 统一时间格式：将 "yyyy-MM-dd hh:mm:ss.fff" 转换为 "yyyy-MM-dd hh:mm:ss.f"
    # 标准化格式的时间精度为0.1秒（1位小数）
    time_col = standard_columns[0]
    print(f"[INFO] 处理时间格式列: '{time_col}'")
    
    # 检查时间列的数据类型
    print(f"[INFO] 时间列数据类型: {std_df[time_col].dtype}")
    print(f"[INFO] 时间列前3个值: {std_df[time_col].head(3).tolist()}")
    
    # 转换为字符串并统一时间格式
    std_df[time_col] = std_df[time_col].astype(str).str.strip()
    
    # 统一时间格式为 yyyy-MM-dd hh:mm:ss.f（保留1位小数）
    # 使用正则表达式处理各种时间格式
    std_df[time_col] = std_df[time_col].str.replace(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d+)', 
        lambda m: m.group(1) + '.' + m.group(2)[0], 
        regex=True
    )
    
    print(f"[INFO] 时间格式转换后前3个值: {std_df[time_col].head(3).tolist()}")
    
    # 6. 输出标准化格式文件
    if output_file is None:
        base_name = os.path.basename(input_file)
        name_no_ext = os.path.splitext(base_name)[0]
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{name_no_ext}_converted.csv")
    
    std_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n[SUCCESS] 转换完成！")
    print(f"[SUCCESS] 输出文件: {output_file}")
    print(f"[SUCCESS] 输出列数: {len(std_df.columns)}")
    print(f"[SUCCESS] 输出行数: {len(std_df)}")
    
    print(f"\n[VERIFY] 前3行预览:")
    print(std_df.head(3).to_string())
    
    return output_file


def verify_output(output_file, reference_file=None):
    """验证输出文件格式是否与标准化格式一致"""
    print(f"\n[VERIFY] 验证输出文件格式...")
    
    output_df = pd.read_csv(output_file, encoding='utf-8-sig')
    
    expected_cols = 145
    actual_cols = len(output_df.columns)
    
    if actual_cols == expected_cols:
        print(f"[VERIFY PASS] 列数匹配: {actual_cols} (预期: {expected_cols})")
    else:
        print(f"[VERIFY FAIL] 列数不匹配: {actual_cols} (预期: {expected_cols})")
    
    first_col = output_df.columns[0]
    first_col_expected = '星上时间'
    if first_col == first_col_expected:
        print(f"[VERIFY PASS] 第一列名称正确: '{first_col}'")
    else:
        print(f"[VERIFY FAIL] 第一列名称不正确: '{first_col}' (预期: '{first_col_expected}')")
    
    if reference_file and os.path.exists(reference_file):
        try:
            ref_df = pd.read_csv(reference_file, encoding='gbk')
            ref_cols = list(ref_df.columns)
            out_cols = list(output_df.columns)
            
            if ref_cols == out_cols:
                print(f"[VERIFY PASS] 列名与参考文件完全匹配")
            else:
                ref_set = set(ref_cols)
                out_set = set(out_cols)
                missing = ref_set - out_set
                extra = out_set - ref_set
                if missing:
                    print(f"[VERIFY WARN] 参考文件中有但输出中缺失的列: {missing}")
                if extra:
                    print(f"[VERIFY WARN] 输出中有但参考文件中没有的列: {extra}")
        except Exception as e:
            print(f"[VERIFY WARN] 无法读取参考文件: {e}")
    
    # 验证时间格式
    time_col = output_df.columns[0]
    sample_times = output_df[time_col].head(5).tolist()
    print(f"[VERIFY] 时间列样例: {sample_times}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='卫星遥测参数日志格式转换工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例:
  python convert_log.py --data target/PACK_3_0058_ss_20251030_67240194.csv
  python convert_log.py --data target/PACK_3_0058_ss_20251030_67240194.csv --output output/converted.csv
  python convert_log.py --data target/PACK_3_0058_ss_20251030_67240194.csv --encoding gbk
        """
    )
    
    parser.add_argument('--data', type=str, required=True,
                        help='要转换的目标日志文件路径')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（可选）')
    parser.add_argument('--encoding', type=str, default='utf-8',
                        help='文件编码，默认utf-8')
    parser.add_argument('--verify', action='store_true', default=True,
                        help='转换后验证格式')
    
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(script_dir)
    reference_file = os.path.join(skill_dir, 'reference', 'standard_log2.csv')
    
    output_file = convert_log(args.data, args.output, args.encoding)
    
    if args.verify:
        verify_output(output_file, reference_file)
    
    print(f"\n[DONE] 日志格式转换完成！")


if __name__ == '__main__':
    main()