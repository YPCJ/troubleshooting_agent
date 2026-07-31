import json
import sys

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

max_values = {}
min_values = {}
counts = {}

for item in data:
    para = item['para_name']
    points = item['value']
    
    if len(points) == 0:
        continue
        
    vals = [float(p['point_value']) for p in points]
    
    max_values[para] = max(vals)
    min_values[para] = min(vals)
    counts[para] = len(vals)

print("Counts:", counts)
print("Max values:", max_values)
print("Min values:", min_values)
