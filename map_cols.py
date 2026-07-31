import pandas as pd
import json

standard_df = pd.read_csv('skills/format_transform/reference/standard_log2.csv', encoding='gbk', nrows=1)
standard_cols = list(standard_df.columns)

target_df = pd.read_csv('skills/format_transform/target/PACK_12_0058_ss_20250824_100794625.csv', encoding='utf-8', nrows=1)
target_cols = list(target_df.columns)
target_telemetry = target_cols[12:]

with open('map_cols.out', 'w') as f:
    f.write("Standard cols:\n")
    for i, c in enumerate(standard_cols):
        f.write(f"{i}: {c}\n")
    f.write("\nTarget telemetry cols:\n")
    for i, c in enumerate(target_telemetry):
        f.write(f"{i}: {c}\n")
