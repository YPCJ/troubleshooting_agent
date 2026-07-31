import csv

with open('skills/format_transform/reference/standard_log2.csv', 'r', encoding='gbk') as f:
    reader = csv.reader(f)
    print("Standard headers:", next(reader))
