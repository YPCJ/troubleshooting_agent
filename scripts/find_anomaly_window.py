import json
import sys

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

for item in data:
    para = item['para_name']
    points = item['value']
    if not points:
        print(f"{para}: no data")
        continue
    exceed = [p for p in points if float(p['point_value']) >= threshold]
    if not exceed:
        print(f"{para}: no points >= {threshold}")
        continue
    print(f"{para}: {len(exceed)} points >= {threshold}")
    print(f"  first exceed: {exceed[0]['time']} = {exceed[0]['point_value']}")
    print(f"  last  exceed: {exceed[-1]['time']} = {exceed[-1]['point_value']}")
    print(f"  data start: {points[0]['time']}, data end: {points[-1]['time']}")
