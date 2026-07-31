import json
import sys

def get_min_max(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    values = [float(pt['point_value']) for pt in data[0]['value']]
    return min(values), max(values)

print(get_min_max(sys.argv[1]))
