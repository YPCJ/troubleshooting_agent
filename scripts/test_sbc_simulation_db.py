"""Small, synthetic feeder scenarios independent of orbital pass generation."""

import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import patch

import generate_sbc_simulation_db as simulation


DAY_MS = 86_400_000
HOUR_MS = 3_600_000


def timestamp(hour):
    return (datetime(2026, 8, 8) + timedelta(hours=hour)).isoformat(
        sep=" ", timespec="milliseconds"
    )


class TemporalServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(simulation.SCHEMA)
        simulation.insert_metadata(self.connection)
        simulation.insert_resources(self.connection)
        self.arcs = simulation.build_directed_arcs(simulation.build_edges())
        simulation.insert_topologies(self.connection, self.arcs)

    def add_pass(self, satellite, start, end, gateway="TJS"):
        gateway_name = self.connection.execute(
            "SELECT gateway_name FROM protocol_gateway_basic_info WHERE gateway_id=?",
            (gateway,),
        ).fetchone()[0]
        return self.connection.execute(
            """INSERT INTO ground_link_topology(
                link_name, planning_constellation, constellation, orbit_number,
                planned_start_bdt, actual_start_bdt, planned_end_bdt, actual_end_bdt,
                feeder_realtime_status, upload_start_status, upload_end_status,
                source_node_name, source_port, destination_node_name, destination_port,
                link_direction, total_bandwidth_mbps, feeder_connectivity,
                landing_satellite_id, gateway_id, tracking_arc_id, peak_bdt, peak_elevation_deg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"TEST-{satellite}-{gateway}-{start}",
                simulation.CONSTELLATION, simulation.CONSTELLATION, 1,
                timestamp(start), timestamp(start), timestamp(end), timestamp(end),
                "正常", "上注完成", "上注完成",
                simulation.satellite_name(satellite), "FEEDER-01", gateway_name,
                f"RF-{satellite}", "双向", 10000, "连通",
                satellite, gateway, f"TEST-ARC-{satellite}-{gateway}-{start}",
                timestamp((start + end) / 2), 45.0,
            ),
        ).lastrowid

    def intervals(self, actual=True):
        return simulation.derive_service_intervals(self.connection, actual=actual)

    def totals(self, satellite, actual=True):
        suffix = "actual" if actual else "theoretical"
        unavailable = "actual" if actual else "planned"
        return tuple(self.connection.execute(
            f"""SELECT SUM(local_{suffix}_duration_seconds),
                       SUM(cross_satellite_{suffix}_duration_seconds),
                       SUM({unavailable}_unavailable_duration_seconds),
                       SUM(interruption_count)
                FROM connectionless_continuity_statistics WHERE satellite_id=?""",
            (satellite,),
        ).fetchone())

    def gaps(self, satellite):
        return [tuple(row) for row in self.connection.execute(
            """SELECT interruption_start_bdt, interruption_end_bdt, interruption_seconds
               FROM v_keepalive_interruptions WHERE satellite_id=?
               ORDER BY interruption_start_bdt""",
            (satellite,),
        )]

    def selected(self, satellite):
        return self.connection.execute(
            """SELECT * FROM keepalive_landing_candidate
               WHERE source_satellite_id=? AND is_selected=1 ORDER BY valid_start_bdt""",
            (satellite,),
        ).fetchall()

    def test_no_feeders_produces_full_day_unavailability_for_all_60_satellites(self):
        for actual in (False, True):
            intervals = self.intervals(actual)
            self.assertEqual(len(intervals), 60)
            for satellite, rows in intervals.items():
                with self.subTest(actual=actual, satellite=satellite):
                    self.assertEqual(
                        [(row.start_ms, row.end_ms, row.choices) for row in rows],
                        [(0, DAY_MS, ())],
                    )
        simulation.insert_temporal_services(self.connection)
        for table in ("keepalive_landing_candidate", "keepalive_statistics",
                      "station_selection_route", "v_selected_keepalive_landing"):
            self.assertEqual(
                self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
            )
        for satellite in simulation.satellite_ids():
            self.assertEqual(self.totals(satellite), (0, 0, 86400, 0))
            self.assertEqual(self.totals(satellite, False), (0, 0, 86400, 0))
            self.assertEqual(self.gaps(satellite), [(timestamp(0), timestamp(24), 86400)])

    def test_single_pass_has_exact_local_cross_and_day_edge_durations(self):
        link_id = self.add_pass("A0101", 10, 11)
        for actual in (False, True):
            for satellite, intervals in self.intervals(actual).items():
                with self.subTest(actual=actual, satellite=satellite):
                    self.assertEqual(
                        [(row.start_ms, row.end_ms) for row in intervals],
                        [(0, 10 * HOUR_MS), (10 * HOUR_MS, 11 * HOUR_MS),
                         (11 * HOUR_MS, DAY_MS)],
                    )
                    self.assertFalse(intervals[0].choices)
                    self.assertFalse(intervals[2].choices)
                    choice, = intervals[1].choices
                    self.assertEqual(choice.ground_link_id, link_id)
                    self.assertEqual(choice.path[0], satellite)
                    self.assertEqual(choice.path[-1], "A0101")
                    self.assertEqual(len(choice.path) == 1, satellite == "A0101")
        simulation.insert_temporal_services(self.connection)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM station_selection_route").fetchone()[0],
            60,
        )
        for satellite in simulation.satellite_ids():
            expected = (3600, 0, 82800, 0) if satellite == "A0101" else (0, 3600, 82800, 0)
            self.assertEqual(self.totals(satellite), expected)
            self.assertEqual(self.totals(satellite, False), expected)
            self.assertEqual(self.gaps(satellite), [
                (timestamp(0), timestamp(10), 36000),
                (timestamp(11), timestamp(24), 46800),
            ])
            selected, = self.selected(satellite)
            self.assertEqual(
                (selected["valid_start_bdt"], selected["valid_end_bdt"]),
                (timestamp(10), timestamp(11)),
            )

    def test_sticky_landing_does_not_handover_while_current_arc_active(self):
        # A0101 has a TJS arc 10-11 and an overlapping GZS arc 10.5-11.5.
        # Under sticky routing the held TJS landing is kept through 11:00 even
        # though GZS is also reachable; handover only happens after a gap.
        self.add_pass("A0101", 10, 11, "TJS")
        self.add_pass("A0101", 10.5, 11.5, "GZS")
        simulation.insert_temporal_services(self.connection)
        for satellite in simulation.satellite_ids():
            selected = self.selected(satellite)
            # Selected candidate stays TJS for the full 10-11 window (no mid-arc handover).
            self.assertTrue(selected)
            self.assertEqual(selected[0]["gateway_id"], "TJS")
            self.assertEqual(selected[0]["valid_start_bdt"], timestamp(10))
            # During the overlapping window 10.5-11 there is exactly ONE selected landing.
            overlapping = [row for row in selected
                           if row["valid_start_bdt"] <= timestamp(10.5) < row["valid_end_bdt"]]
            self.assertEqual(len(overlapping), 1)
            self.assertEqual(overlapping[0]["gateway_id"], "TJS")

    def test_handover_only_after_service_gap(self):
        # Two disjoint arcs for A0101 with a gap: handover happens at the gap.
        self.add_pass("A0101", 10, 11, "TJS")
        self.add_pass("A0101", 12, 13, "GZS")
        simulation.insert_temporal_services(self.connection)
        selected = self.selected("A0101")
        self.assertEqual([row["gateway_id"] for row in selected], ["TJS", "GZS"])
        self.assertEqual(selected[0]["valid_end_bdt"], timestamp(11))
        self.assertEqual(selected[1]["valid_start_bdt"], timestamp(12))
        # No interruption counted across the gap boundary.
        self.assertEqual(self.totals("A0101")[3], 0)

    def test_isolation_without_own_feeder_prevents_cross_service_until_1500(self):
        self.add_pass("A0101", 11, 16)
        for actual in (False, True):
            intervals = self.intervals(actual)["A0603"]
            self.assertEqual(
                [(row.start_ms // HOUR_MS, row.end_ms // HOUR_MS, bool(row.choices))
                 for row in intervals],
                [(0, 11, False), (11, 12, True), (12, 15, False),
                 (15, 16, True), (16, 24, False)],
            )
        simulation.insert_temporal_services(self.connection)
        self.assertEqual(self.totals("A0603"), (0, 7200, 79200, 0))
        self.assertEqual(self.totals("A0602"), (0, 18000, 68400, 0))
        self.assertEqual(self.gaps("A0603"), [
            (timestamp(0), timestamp(11), 39600),
            (timestamp(12), timestamp(15), 10800),
            (timestamp(16), timestamp(24), 28800),
        ])

    def test_isolated_satellite_can_use_own_feeder_but_cannot_forward_for_others(self):
        self.add_pass("A0101", 11, 16)
        own_link = self.add_pass("A0603", 13, 14, "GZS")
        for actual in (False, True):
            intervals = self.intervals(actual)
            own_interval = next(row for row in intervals["A0603"]
                                if row.start_ms == 13 * HOUR_MS)
            own_choice, = own_interval.choices
            self.assertEqual(own_choice.path, ("A0603",))
            self.assertEqual(own_choice.ground_link_id, own_link)
            for satellite, rows in intervals.items():
                if satellite != "A0603":
                    self.assertFalse(any(choice.ground_link_id == own_link
                                         for row in rows for choice in row.choices))
        simulation.insert_temporal_services(self.connection)
        self.assertEqual(self.totals("A0603"), (3600, 7200, 75600, 0))
        self.assertEqual(self.totals("A0603", False), (3600, 7200, 75600, 0))
        candidates = self.connection.execute(
            "SELECT route_path_json FROM keepalive_landing_candidate WHERE ground_link_id=?",
            (own_link,),
        ).fetchall()
        self.assertEqual([json.loads(row[0]) for row in candidates], [["A0603"]])

    def test_asymmetric_graph_uses_forward_reachability_not_reverse_edges(self):
        self.add_pass("A0102", 10, 11)
        self.connection.execute(
            "UPDATE topology_edge SET is_connected=0 WHERE topology_kind='实时'"
        )
        self.connection.execute(
            """UPDATE topology_edge SET is_connected=1 WHERE topology_kind='实时'
               AND ((source_satellite_id='A0101' AND destination_satellite_id='A0102')
                 OR (source_satellite_id='A0102' AND destination_satellite_id='A0103'))"""
        )
        adjacency = {satellite: set() for satellite in simulation.satellite_ids()}
        adjacency["A0101"].add("A0102")
        adjacency["A0102"].add("A0103")
        self.connection.execute(
            "UPDATE realtime_topology SET matrix_json=?",
            (simulation.matrix_json(adjacency),),
        )
        intervals = self.intervals()
        self.assertEqual(intervals["A0101"][1].choices[0].path, ("A0101", "A0102"))
        self.assertEqual(intervals["A0102"][1].choices[0].path, ("A0102",))
        self.assertEqual(
            [(row.start_ms, row.end_ms, row.choices) for row in intervals["A0103"]],
            [(0, DAY_MS, ())],
        )
        simulation.insert_temporal_services(self.connection)
        self.assertEqual(self.totals("A0101"), (0, 3600, 82800, 0))
        self.assertEqual(self.totals("A0103"), (0, 0, 86400, 1))
        self.assertEqual(self.totals("A0103", False), (0, 3600, 82800, 1))
        sources = {row[0] for row in self.connection.execute(
            "SELECT DISTINCT source_satellite_id FROM keepalive_landing_candidate"
        )}
        self.assertEqual(sources, {"A0101", "A0102"})

    def test_touching_pass_handover_does_not_count_as_interruption(self):
        self.add_pass("A0101", 10, 11)
        self.add_pass("A0102", 11, 12)
        simulation.insert_temporal_services(self.connection)
        self.assertEqual(self.totals("A0101"), (3600, 3600, 79200, 0))
        self.assertEqual(self.totals("A0102"), (3600, 3600, 79200, 0))
        self.assertEqual(self.totals("A0201"), (0, 7200, 79200, 0))
        for satellite in simulation.satellite_ids():
            self.assertEqual(self.totals(satellite)[3], 0)
            self.assertEqual(self.gaps(satellite), [
                (timestamp(0), timestamp(10), 36000),
                (timestamp(12), timestamp(24), 43200),
            ])
            first, second = self.selected(satellite)
            self.assertEqual(first["valid_end_bdt"], second["valid_start_bdt"])
            self.assertEqual(
                (first["landing_satellite_id"], second["landing_satellite_id"]),
                ("A0101", "A0102"),
            )

    def test_delayed_actual_pass_records_one_outage_and_conserves_both_timelines(self):
        link = self.add_pass("A0101", 10, 11)
        self.connection.execute(
            "UPDATE ground_link_topology SET actual_start_bdt=? WHERE ground_link_id=?",
            (timestamp(10.25), link),
        )
        simulation.insert_temporal_services(self.connection)
        for satellite in simulation.satellite_ids():
            local = satellite == "A0101"
            self.assertEqual(self.totals(satellite),
                             (2700 if local else 0, 0 if local else 2700, 83700, 1))
            self.assertEqual(self.totals(satellite, False),
                             (3600 if local else 0, 0 if local else 3600, 82800, 1))
            for actual in (False, True):
                self.assertEqual(sum(self.totals(satellite, actual)[:3]), 86400)

    def test_router_and_laser_telemetry_follow_half_open_planned_changes(self):
        self.add_pass("A0101", 0, 24)
        self.add_pass("A0603", 13, 14, "GZS")
        simulation.insert_temporal_services(self.connection)
        simulation.insert_operational_baseline(
            self.connection,
            self.arcs,
            simulation.FaultScenario(
                laser_fault_satellite="A0306",
                route_loss_satellite="A0303",
                feeder_fault_link_id=1,
                feeder_fault_link_name="TEST-LINK",
                feeder_fault_landing_satellite="A0101",
                feeder_fault_gateway_id="TJS",
            ),
        )
        simulation.insert_telemetry(self.connection)
        for hour, expected in ((11, "2"), (12, "0"), (13, "1"), (14, "0"), (15, "2")):
            row = self.connection.execute(
                """SELECT raw_value, parameter_result FROM router_telemetry
                   WHERE telemetry_source='A0603' AND parameter_code='RTR-LANDING-MODE'
                   AND reported_bdt=?""", (timestamp(hour),),
            ).fetchone()
            self.assertEqual(tuple(row), (expected, "正常"))
        for terminal in ("A0603-L-UP", "A0603-L-DOWN", "A0603-L-LEFT", "A0503-L-RIGHT"):
            for hour, expected in ((11, ("1", "锁定")), (12, ("0", "规划断链")),
                                   (14, ("0", "规划断链")), (15, ("1", "锁定"))):
                row = self.connection.execute(
                    """SELECT raw_value, parsed_value, parameter_result FROM laser_telemetry
                       WHERE laser_terminal_id=? AND reported_bdt=?""",
                    (terminal, timestamp(hour)),
                ).fetchone()
                self.assertEqual(tuple(row), (*expected, "正常"))
        idle_rows = self.connection.execute(
            """SELECT raw_value, parsed_value, parameter_result FROM laser_telemetry
               JOIN laser_terminal USING (laser_terminal_id)
               WHERE terminal_status='空闲'"""
        ).fetchall()
        self.assertEqual(len(idle_rows), 20 * 24)
        self.assertEqual({tuple(row) for row in idle_rows}, {("0", "空闲", "正常")})


class ObservationTableTests(unittest.TestCase):
    setUp = TemporalServiceTests.setUp
    add_pass = TemporalServiceTests.add_pass

    def snapshots(self, satellite, hour):
        row = self.connection.execute(
            """SELECT entries_json FROM onboard_routing_table_snapshot
               WHERE satellite_id=? AND queried_bdt=?""", (satellite, timestamp(hour)),
        ).fetchone()
        return json.loads(row[0])

    def add_laser_event(self, arc, hour, connected):
        source, source_laser, destination, destination_laser = arc
        self.connection.execute(
            """INSERT INTO laser_link_event(
                satellite_a_name, satellite_a_id, laser_a_id, satellite_b_name,
                satellite_b_id, laser_b_id, changed_bdt, link_status, link_rate_mbps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, source, source_laser, destination, destination, destination_laser,
             timestamp(hour), "连通" if connected else "中断", 10000 if connected else 0),
        )

    def test_uplink_receipt_pair_and_failed_feeder_without_fabricated_candidate(self):
        normal = self.add_pass("A0101", 10, 11)
        failed = self.add_pass("A0102", 11, 12)
        self.connection.execute(
            """UPDATE ground_link_topology SET feeder_connectivity='中断',
               feeder_realtime_status='中断', upload_start_status='上注异常',
               upload_end_status='上注异常' WHERE ground_link_id=?""", (failed,),
        )
        simulation.insert_temporal_services(self.connection)
        simulation.insert_landing_table_updates(self.connection)
        rows = self.connection.execute(
            "SELECT * FROM landing_table_update_observation ORDER BY observation_id"
        ).fetchall()
        uplink, receipt, *missing_receipts = rows
        self.assertEqual((uplink["ground_link_id"], receipt["ground_link_id"]), (normal, normal))
        self.assertEqual(uplink["update_id"], receipt["update_id"])
        self.assertEqual((uplink["attempt_no"], receipt["attempt_no"]), (1, 1))
        self.assertEqual((uplink["event_type"], receipt["event_type"]), ("uplink", "receipt_diffusion"))
        self.assertEqual(uplink["observed_bdt"], timestamp(10))
        self.assertEqual(receipt["observed_bdt"], timestamp(10 + 1 / 3600))
        self.assertEqual(len(json.loads(uplink["candidate_ids_json"])), 60)
        self.assertEqual(len(missing_receipts), 1200)
        self.assertTrue(all(row["ground_link_id"] == failed for row in missing_receipts))
        self.assertTrue(all(row["event_type"] == "uplink" for row in missing_receipts))
        self.assertTrue(all(row["candidate_ids_json"] == "[]" for row in missing_receipts))
        self.assertEqual(
            [row["attempt_no"] for row in missing_receipts],
            list(range(1, 1201)),
        )
        self.assertEqual(missing_receipts[-1]["observed_bdt"], timestamp(12 - 3 / 3600))
        simulation.insert_onboard_routing_snapshots(self.connection)
        simulation.verify_observation_tables(self.connection)

    def test_versions_follow_candidate_boundaries_and_receipts_are_not_backdated(self):
        link = self.add_pass("A0101", 11, 16)
        simulation.insert_temporal_services(self.connection)
        simulation.insert_landing_table_updates(self.connection)
        uplinks = self.connection.execute(
            """SELECT * FROM landing_table_update_observation
               WHERE event_type='uplink' ORDER BY observed_bdt"""
        ).fetchall()
        self.assertEqual([row["observed_bdt"] for row in uplinks],
                         [timestamp(11), timestamp(12), timestamp(15)])
        self.assertEqual(len({row["update_id"] for row in uplinks}), 3)
        for row in uplinks:
            self.assertEqual(row["ground_link_id"], link)
            for candidate_id in json.loads(row["candidate_ids_json"]):
                candidate = self.connection.execute(
                    "SELECT * FROM keepalive_landing_candidate WHERE candidate_id=?", (candidate_id,)
                ).fetchone()
                self.assertLessEqual(candidate["valid_start_bdt"], row["observed_bdt"])
                self.assertLess(row["observed_bdt"], candidate["valid_end_bdt"])

    def test_delayed_establishment_and_too_short_arcs_never_invent_early_receipts(self):
        delayed = self.add_pass("A0101", 10, 11)
        short = self.add_pass("A0102", 11, 11 + 0.5 / 3600)
        self.connection.execute(
            "UPDATE ground_link_topology SET actual_start_bdt=? WHERE ground_link_id=?",
            (timestamp(10.25), delayed),
        )
        simulation.insert_temporal_services(self.connection)
        simulation.insert_landing_table_updates(self.connection)
        receipts = self.connection.execute(
            "SELECT * FROM landing_table_update_observation WHERE event_type='receipt_diffusion'"
        ).fetchall()
        self.assertTrue(receipts)
        self.assertTrue(all(row["observed_bdt"] > timestamp(10.25) for row in receipts))
        self.assertFalse(any(row["ground_link_id"] == short for row in receipts))
        delayed_uplinks = self.connection.execute(
            """SELECT * FROM landing_table_update_observation
               WHERE ground_link_id=? AND event_type='uplink' ORDER BY observed_bdt""",
            (delayed,),
        ).fetchall()
        self.assertEqual(len(delayed_uplinks), 301)
        self.assertEqual(delayed_uplinks[-1]["observed_bdt"], timestamp(10.25))

    def test_half_hour_all_destinations_shortest_hops_and_route_loss_are_local(self):
        # Baseline physical observations remain connected while realtime forwarding
        # reachability includes route loss. Do not turn that into a laser failure.
        scenario = simulation.FaultScenario("A0504", "A0306", 1, "test", "A0101", "TJS")
        simulation.reconfigure_realtime_topology_for_faults(self.connection, self.arcs, scenario)
        for arc in self.arcs:
            self.add_laser_event(arc, 0, True)
            if "A0504" in (arc[0], arc[2]):
                self.add_laser_event(arc, 17 + 20 / 60, False)
                self.add_laser_event(arc, 19 + 10 / 60, True)
        simulation.insert_onboard_routing_snapshots(self.connection)
        simulation.verify_observation_tables(self.connection)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM onboard_routing_table_snapshot"
        ).fetchone()[0], 2880)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM onboard_routing_table_snapshot WHERE entries_json='[]'"
        ).fetchone()[0], 4)
        for hour in (18, 18.5, 19, 19.5):
            self.assertEqual(self.snapshots("A0306", hour), [])
            self.assertEqual(len(self.snapshots("A0305", hour)), 59)
            target = next(entry for entry in self.snapshots("A0305", hour)
                          if entry["destination_satellite_id"] == "A0306")
            self.assertTrue(target["reachable"])
            self.assertTrue(any(
                "A0306" in entry["path"][1:-1]
                for satellite in simulation.satellite_ids() if satellite != "A0306"
                for entry in self.snapshots(satellite, hour)
            ))
        for hour in (17.5, 20):
            self.assertEqual(len(self.snapshots("A0306", hour)), 59)
        self.assertTrue(all(not row["reachable"] for row in self.snapshots("A0603", 12)))
        self.assertTrue(all(row["reachable"] for row in self.snapshots("A0603", 15)))
        self.assertTrue(all(row["reachable"] for row in self.snapshots("A0504", 17)))
        self.assertTrue(all(not row["reachable"] for row in self.snapshots("A0504", 17.5)))
        self.assertTrue(all(not row["reachable"] for row in self.snapshots("A0504", 19)))
        self.assertTrue(all(row["reachable"] for row in self.snapshots("A0504", 19.5)))
        for query_time, adjacency in simulation.routing_observation_graphs(self.connection):
            # Independent relaxation verifies minimal hop counts, not just valid paths.
            for source in simulation.satellite_ids():
                entries = json.loads(self.connection.execute(
                    """SELECT entries_json FROM onboard_routing_table_snapshot
                       WHERE satellite_id=? AND queried_bdt=?""", (source, query_time),
                ).fetchone()[0])
                distances = {source: 0}
                for _ in range(59):
                    changed = False
                    for node, neighbors in adjacency.items():
                        if node not in distances:
                            continue
                        for neighbor in neighbors:
                            if distances.get(neighbor, 60) > distances[node] + 1:
                                distances[neighbor] = distances[node] + 1
                                changed = True
                    if not changed:
                        break
                for entry in entries:
                    destination = entry["destination_satellite_id"]
                    self.assertEqual(entry["hop_count"], distances.get(destination))
                    self.assertNotEqual(source, destination)
                    if destination in distances:
                        path = entry["path"]
                        self.assertEqual((path[0], path[-1]), (source, destination))
                        self.assertEqual(len(path) - 1, entry["hop_count"])
                        self.assertEqual(entry["next_hop_satellite_id"], path[1])
                        self.assertTrue(all(b in adjacency[a] for a, b in zip(path, path[1:])))
                    else:
                        self.assertEqual(entry["path"], [])
                        self.assertIsNone(entry["next_hop_satellite_id"])
        self.assertEqual({row[0] for row in self.connection.execute(
            "SELECT change_source FROM realtime_topology"
        )}, {"星间拓扑状态采集"})

    def test_routing_fallback_respects_directed_realtime_edges(self):
        self.connection.execute("UPDATE topology_edge SET is_connected=0 WHERE topology_kind='实时'")
        self.connection.execute(
            """UPDATE topology_edge SET is_connected=1 WHERE topology_kind='实时'
               AND source_satellite_id='A0101' AND destination_satellite_id='A0102'"""
        )
        simulation.insert_onboard_routing_snapshots(self.connection, None)
        forward = next(row for row in self.snapshots("A0101", 0)
                       if row["destination_satellite_id"] == "A0102")
        backward = next(row for row in self.snapshots("A0102", 0)
                        if row["destination_satellite_id"] == "A0101")
        self.assertEqual(forward["hop_count"], 1)
        self.assertFalse(backward["reachable"])

    def test_enrichment_is_additive_atomic_and_preserves_caller_transaction(self):
        # Construct an old-schema database in memory, rather than modifying a live DB.
        old_schema = simulation.SCHEMA.split("CREATE TABLE landing_table_update_observation")[0]
        with closing(sqlite3.connect(":memory:")) as old:
            old.row_factory = sqlite3.Row
            old.executescript(old_schema)
            simulation.insert_resources(old)
            simulation.insert_topologies(old, self.arcs)
            old.commit()
            tables = [row[0] for row in old.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            before = {table: [tuple(row) for row in old.execute(f"SELECT * FROM {table}")]
                      for table in tables}
            with patch.object(simulation, "insert_onboard_routing_snapshots",
                              side_effect=RuntimeError("synthetic failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    simulation.enrich_observation_tables(old)
            self.assertIsNone(old.execute(
                "SELECT 1 FROM sqlite_master WHERE name='landing_table_update_observation'"
            ).fetchone())
            old.execute("BEGIN")
            simulation.enrich_observation_tables(old)
            self.assertTrue(old.in_transaction)
            old.rollback()
            self.assertIsNone(old.execute(
                "SELECT 1 FROM sqlite_master WHERE name='onboard_routing_table_snapshot'"
            ).fetchone())
            simulation.enrich_observation_tables(old)
            self.assertFalse(old.in_transaction)
            for table in tables:
                self.assertEqual(before[table], [tuple(row) for row in old.execute(f"SELECT * FROM {table}")])
            with self.assertRaisesRegex(ValueError, "already exist"):
                simulation.enrich_observation_tables(old)
            simulation.verify_observation_tables(old)

    def test_retry_migration_is_atomic_and_replaces_only_landing_observations(self):
        failed = self.add_pass("A0102", 11, 12)
        self.connection.execute(
            """UPDATE ground_link_topology SET feeder_connectivity='中断',
               feeder_realtime_status='中断', upload_start_status='上注异常',
               upload_end_status='上注异常' WHERE ground_link_id=?""",
            (failed,),
        )
        simulation.insert_temporal_services(self.connection)
        self.connection.execute("DROP TABLE landing_table_update_observation")
        self.connection.execute("""CREATE TABLE landing_table_update_observation(
            observation_id INTEGER PRIMARY KEY,
            update_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            observed_bdt TEXT NOT NULL,
            landing_satellite_id TEXT NOT NULL,
            gateway_id TEXT NOT NULL,
            ground_link_id INTEGER NOT NULL,
            tracking_arc_id TEXT NOT NULL,
            candidate_ids_json TEXT NOT NULL,
            UNIQUE(update_id, event_type)
        )""")
        self.connection.execute(
            """INSERT INTO landing_table_update_observation VALUES(
               1, 'legacy', 'uplink', ?, 'A0102', 'TJS', ?, 'TEST-ARC', '[]')""",
            (timestamp(11), failed),
        )
        with patch.object(
            simulation, "insert_landing_table_updates",
            side_effect=RuntimeError("synthetic retry migration failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic retry migration failure"):
                simulation.replace_landing_updates_with_retries(self.connection)
        self.assertNotIn(
            "attempt_no",
            {row[1] for row in self.connection.execute(
                "PRAGMA table_info(landing_table_update_observation)"
            )},
        )
        self.assertEqual(
            "legacy",
            self.connection.execute(
                "SELECT update_id FROM landing_table_update_observation"
            ).fetchone()[0],
        )
        simulation.replace_landing_updates_with_retries(self.connection)
        migrated = self.connection.execute(
            """SELECT COUNT(*), MIN(attempt_no), MAX(attempt_no)
               FROM landing_table_update_observation
               WHERE ground_link_id=? AND event_type='uplink'""",
            (failed,),
        ).fetchone()
        self.assertEqual((1200, 1, 1200), tuple(migrated))


if __name__ == "__main__":
    unittest.main()
