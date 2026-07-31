#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import argparse
import os
import sys
import difflib
import json
import warnings
warnings.filterwarnings('ignore')

def get_best_match(std_col, target_cols, threshold=0.3):
    # Manual mappings for known tricky ones
    manual_map = {
        'S/C相控阵天线测温点': 'SC频段舱外天线测温',
        '蓄电池A测点1': '蓄电池1主份测温',
        '蓄电池A测点2': '蓄电池1备份测温',
        '蓄电池B测点1': '蓄电池2主份测温',
        '蓄电池B测点2': '蓄电池2备份测温',
        '蓄电池C测点1': '蓄电池3主份测温',
        '蓄电池C测点2': '蓄电池3备份测温',
        '蓄电池D测点1': '蓄电池4主份测温',
        '蓄电池D测点2': '蓄电池4备份测温',
        '蓄电池E测点1': '蓄电池5主份测温',
        '蓄电池E测点2': '蓄电池5备份测温',
        '蓄电池F测点1': '蓄电池6主份测温',
        '蓄电池F测点2': '蓄电池6备份测温',
        '蓄电池G测点1': '蓄电池7主份测温',
        '蓄电池G测点2': '蓄电池7备份测温',
        'PPCU测点': 'PPCU测温1',
        'Ka发射相控阵天线测点': 'Ka发射天线测温',
        'Ka接收相控阵天线测点': 'Ka接收天线测温',
        '星敏感器A测点': '星敏感器支架1测温',
        '星敏感器B测点': '星敏感器支架2测温',
        '星敏感器C测点': '星敏感器支架3测温',
        '反作用力飞轮A测点': '飞轮测温',
        '气瓶测点1': '气瓶测温1',
        '气瓶测点2': '气瓶测温2',
        '电推管路测点1': '推进管路测温测温',
        '太阳翼A轴SADA测点1': 'A轴热敏1',
        '太阳翼A轴SADA测点2': 'A轴热敏2',
        '太阳翼B轴SADA测点3': 'B轴热敏1',
        '太阳翼B轴SADA测点4': 'B轴热敏2',
        '导航信号滤波与发射设备测点': '导航增强滤波与发射设备测温',
        '霍尔推力器测点': '霍尔推力器'
    }
    
    if std_col in manual_map and manual_map[std_col] in target_cols:
        return manual_map[std_col]
        
    # Pattern matching for S/C antenna
    if std_col.startswith('S/C相控阵天线测温点'):
        num = std_col.replace('S/C相控阵天线测温点', '')
        cand = f'SC频段舱外天线测温{num}'
        if cand in target_cols: return cand
        
    # Pattern matching for NZ
    if std_col.startswith('NZ舱板'):
        matches = [c for c in target_cols if c.startswith('-Z舱板')]
        if matches:
            # Just return the highest fuzzy match among -Z ones
            best = difflib.get_close_matches(std_col, matches, n=1, cutoff=0.1)
            if best: return best[0]
            
    # Pattern matching for PZ
    if std_col.startswith('PZ舱板'):
        matches = [c for c in target_cols if c.startswith('+Z盖板')]
        if matches:
            best = difflib.get_close_matches(std_col, matches, n=1, cutoff=0.1)
            if best: return best[0]
            
    # Pattern matching for 一线测温
    if std_col.startswith('一线测温'):
        num = std_col.replace('一线测温', '')
        cand = f'一线测温{num}'
        if cand in target_cols: return cand
        
    # Default fuzzy matching
    best = difflib.get_close_matches(std_col, target_cols, n=1, cutoff=threshold)
    if best:
        return best[0]
        
    return None

def convert_log(input_file, reference_file, output_file=None):
    print(f"[INFO] 读取目标文件: {input_file}")
    df_target = pd.read_csv(input_file, encoding='utf-8')
    
    print(f"[INFO] 读取标准参考文件: {reference_file}")
    df_ref = pd.read_csv(reference_file, encoding='gbk', nrows=1)
    standard_cols = list(df_ref.columns)
    
    target_cols = list(df_target.columns)
    
    # 查找星上时间
    time_col_target = None
    if '星上时间' in target_cols:
        time_col_target = '星上时间'
    else:
        for c in target_cols:
            if '时间' in c:
                time_col_target = c
                break
                
    if not time_col_target:
        print("[ERROR] 找不到时间列")
        sys.exit(1)
        
    # 建立映射
    mapped_target_cols = set([time_col_target])
    mapping = {}
    
    for std_col in standard_cols:
        if std_col == '星上时间':
            mapping[std_col] = time_col_target
            continue
            
        best_match = get_best_match(std_col, target_cols)
        if best_match and best_match not in mapped_target_cols:
            mapping[std_col] = best_match
            mapped_target_cols.add(best_match)
        else:
            mapping[std_col] = None
            
    # 识别未映射的目标列（作为 extra data）
    extra_cols = [c for c in target_cols if c not in mapped_target_cols and c not in ['解析时间', '接收时间', '地面时间', '链路', '站号', '版本号', '虚拟信道ID', '虚拟信道帧计数', '回放标识', '奇偶标识', '明密标识']]
    
    print(f"[INFO] 成功映射 {len([v for v in mapping.values() if v])} / {len(standard_cols)} 个标准列")
    print(f"[INFO] 发现 {len(extra_cols)} 个未映射的额外数据列")
    
    # 构建新 DataFrame
    out_data = {}
    
    for std_col in standard_cols:
        t_col = mapping[std_col]
        if t_col:
            out_data[std_col] = df_target[t_col]
        else:
            out_data[std_col] = [None] * len(df_target)
            
    # 处理时间格式
    time_series = df_target[time_col_target].astype(str).str.strip()
    time_series = time_series.str.replace(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d+)', 
        lambda m: m.group(1) + '.' + m.group(2)[0], 
        regex=True
    )
    out_data['星上时间'] = time_series
    
    df_out = pd.DataFrame(out_data)
    
    # 合并 extra data
    if extra_cols:
        def merge_extra(row):
            extra_dict = {c: row[c] for c in extra_cols if pd.notna(row[c])}
            return json.dumps(extra_dict, ensure_ascii=False)
        
        df_out['extra data'] = df_target.apply(merge_extra, axis=1)
        
    if output_file is None:
        base_name = os.path.basename(input_file)
        name_no_ext = os.path.splitext(base_name)[0]
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{name_no_ext}_converted.csv")
        
    df_out.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"[SUCCESS] 转换完成，输出文件: {output_file}")
    
def main():
    parser = argparse.ArgumentParser(description='日志格式转换')
    parser.add_argument('--data', required=True)
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_file = os.path.join(os.path.dirname(script_dir), 'reference', 'standard_log2.csv')
    
    convert_log(args.data, ref_file, args.output)

if __name__ == '__main__':
    main()
