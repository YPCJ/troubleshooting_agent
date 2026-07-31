import json
import sys

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

for item in data:
    para = item['para_name']
    values = [float(v['point_value']) for v in item['value']]
    if values:
        print(f"{para}: max={max(values)}, min={min(values)}, count={len(values)}")
    else:
        print(f"{para}: no data")
