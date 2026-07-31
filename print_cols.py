import pandas as pd
df = pd.read_csv('skills/format_transform/target/PACK_12_0058_ss_20250824_100794625.csv', nrows=1)
print(list(df.columns))
