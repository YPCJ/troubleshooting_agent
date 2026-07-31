# -*- coding: utf-8 -*-
import re, json, os
from pathlib import Path

base = Path(__file__).resolve().parent / "skills" / "document_write" / "source"
text = ''
for fname in ['info1.md','info2.md','info3.md']:
    fp = base / fname
    text += open(fp,'r',encoding='utf-8').read() + '\n'

lines = text.split('\n')
records = []
for line in lines:
    sat_tag = '\u8bd5\u9a8c\u536b\u661f'
    if sat_tag in line and line.strip().startswith('|'):
        cols = [c.strip() for c in line.split('|')]
        if len(cols) >= 11:
            try:
                record = {
                    'seq': cols[1],
                    'name': cols[2],
                    'type': cols[3],
                    'sat': cols[4],
                    'subsys': cols[5],
                    'device': cols[6],
                    'param': cols[7],
                    'threshold': cols[8],
                    'level': int(cols[9]),
                    'history': int(cols[10]),
                    '7day': int(cols[11])
                }
                records.append(record)
            except:
                pass

seen = {}
for r in records:
    key = (r['sat'], r['param'])
    if key not in seen or r['7day'] > seen[key]['7day']:
        seen[key] = r

print('Total unique records:', len(seen))
print()

sats = {}
for key, r in seen.items():
    sat = r['sat']
    if sat not in sats:
        sats[sat] = []
    sats[sat].append(r)

for sat, recs in sorted(sats.items()):
    total_7day = sum(r['7day'] for r in recs)
    imp_count = sum(1 for r in recs if r['level'] <= 4)
    print('%s: %d parameters, %d warnings in 7 days, %d important (level<=4)' % (sat, len(recs), total_7day, imp_count))
    for r in recs:
        print('  - param=%s | level=%d | 7day=%d | subsys=%s' % (r['param'], r['level'], r['7day'], r['subsys']))
    print()

for sat, recs in sorted(sats.items()):
    total = sum(r['7day'] for r in recs)
    print('%s total 7-day warnings: %d' % (sat, total))