import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).resolve().parent / 'sbc_simulation_20260808.db')
cur = conn.cursor()

# Query 1: landing paths at 18:00
cur.execute("""
SELECT source_satellite_id, networking_satellite_id, gateway_id, valid_start_bdt, valid_end_bdt
FROM v_selected_keepalive_landing
WHERE valid_start_bdt <= '2026-08-08 18:00:00.000' AND valid_end_bdt >= '2026-08-08 18:00:00.000'
ORDER BY source_satellite_id
""")
print("=== Landing paths at 18:00 ===")
for row in cur:
    print('|'.join(str(x) for x in row))

# Query 2: A0306 routing at 18:00 and 18:30
cur.execute("""
SELECT satellite_id, queried_bdt, entries_json
FROM onboard_routing_table_snapshot
WHERE satellite_id = 'A0306' AND queried_bdt IN ('2026-08-08 18:00:00.000', '2026-08-08 18:30:00.000', '2026-08-08 19:00:00.000', '2026-08-08 19:30:00.000', '2026-08-08 20:00:00.000')
""")
print("\n=== A0306 routing snapshots ===")
for row in cur:
    print(f"{row[0]} | {row[1]} | {row[2][:200]}")

# Query 3: PacketIn around 18:00
cur.execute("""
SELECT packetin_id, event_type, affected_link, occurred_bdt, received_bdt, reporting_satellite_id
FROM packetin_message
WHERE occurred_bdt >= '2026-08-08 17:50:00' AND occurred_bdt <= '2026-08-08 20:10:00'
ORDER BY occurred_bdt
""")
print("\n=== PacketIn around 18:00-20:10 ===")
for row in cur:
    print('|'.join(str(x) for x in row))

# Query 4: feeder links at 18:00
cur.execute("""
SELECT landing_satellite_id, gateway_id, planned_start_bdt, planned_end_bdt, actual_start_bdt, actual_end_bdt, feeder_realtime_status
FROM ground_link_topology
WHERE actual_start_bdt <= '2026-08-08 18:00:00.000' AND actual_end_bdt >= '2026-08-08 18:00:00.000'
ORDER BY landing_satellite_id
""")
print("\n=== Active feeder links at 18:00 ===")
for row in cur:
    print('|'.join(str(x) for x in row))

# Query 5: landing table update around 18:00
cur.execute("""
SELECT observation_id, update_id, event_type, observed_bdt, landing_satellite_id, gateway_id
FROM landing_table_update_observation
WHERE observed_bdt >= '2026-08-08 17:50:00' AND observed_bdt <= '2026-08-08 18:10:00'
ORDER BY observed_bdt
LIMIT 20
""")
print("\n=== Landing table updates around 18:00 ===")
for row in cur:
    print('|'.join(str(x) for x in row))

conn.close()
