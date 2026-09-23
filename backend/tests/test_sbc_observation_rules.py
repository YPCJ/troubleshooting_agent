import sqlite3
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from backend.agents.sbc_network_troubleshooting import sqlite_handlers as handlers
from backend.agents.sbc_network_troubleshooting.observation_rules import (
    group_interruptions,
    match_packetin_boundaries,
    terminal_node_evidence,
)


class ObservationRulesTests(unittest.TestCase):
    def test_terminal_node_is_leaf_of_actual_landing_route_tree(self):
        routes = {
            "A": ["A", "B", "L"],
            "B": ["B", "L"],
            "C": ["C", "B", "L"],
        }
        evidence = terminal_node_evidence("A", routes, {"L"})
        self.assertTrue(evidence["is_terminal"])
        self.assertEqual(["A", "B", "L"], evidence["actual_landing_route"])
        self.assertEqual([], evidence["routed_via_by_satellites"])

        routes["D"] = ["D", "A", "B", "L"]
        evidence = terminal_node_evidence("A", routes, {"L"})
        self.assertFalse(evidence["is_terminal"])
        self.assertEqual(["D"], evidence["routed_via_by_satellites"])
        self.assertFalse(terminal_node_evidence("X", routes, {"L"})["is_terminal"])
        self.assertFalse(terminal_node_evidence("A", routes, set())["is_terminal"])

    def test_terminal_query_uses_actual_routes_and_actual_feeder_time(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE satellite_basic_info(satellite_id TEXT);
            INSERT INTO satellite_basic_info VALUES ('S'),('C'),('D'),('N'),('L');
            CREATE TABLE onboard_routing_table_snapshot(
                satellite_id TEXT, queried_bdt TEXT, entries_json TEXT);
            CREATE TABLE keepalive_landing_candidate(
                candidate_id INTEGER, source_satellite_id TEXT, landing_satellite_id TEXT,
                priority INTEGER, route_path_json TEXT,
                is_selected INTEGER, valid_start_bdt TEXT, valid_end_bdt TEXT,
                ground_link_id INTEGER);
            CREATE TABLE ground_link_topology(ground_link_id INTEGER,
                landing_satellite_id TEXT,
                actual_start_bdt TEXT,actual_end_bdt TEXT,
                feeder_realtime_status TEXT,feeder_connectivity TEXT);
            INSERT INTO ground_link_topology VALUES
                (1,'L','2026-08-08 18:00:00.000','2026-08-08 18:30:00.000','正常','连通');
            INSERT INTO keepalive_landing_candidate VALUES
                (1,'S','L',2,'["S","N","L"]',1,'2026-08-08 18:00:00.000','2026-08-08 19:00:00.000',1),
                (2,'C','L',2,'["C","N","L"]',1,'2026-08-08 18:00:00.000','2026-08-08 19:00:00.000',1),
                (3,'D','L',3,'["D","S","N","L"]',1,'2026-08-08 18:10:00.000','2026-08-08 19:00:00.000',1);
        """)
        snapshots = {
            "S": [{"destination_satellite_id": "L", "reachable": True,
                   "next_hop_satellite_id": "N", "path": ["S", "N", "L"]}],
            "C": [{"destination_satellite_id": "L", "reachable": True,
                   "next_hop_satellite_id": "N", "path": ["C", "N", "L"]}],
            "D": [{"destination_satellite_id": "L", "reachable": True,
                   "next_hop_satellite_id": "S", "path": ["D", "S", "N", "L"]}],
            "N": [{"destination_satellite_id": "L", "reachable": True,
                   "next_hop_satellite_id": "L", "path": ["N", "L"]}],
            "L": [],
        }
        connection.executemany(
            "INSERT INTO onboard_routing_table_snapshot VALUES (?, ?, ?)",
            [(satellite, "2026-08-08 18:00:00.000", json.dumps(entries))
             for satellite, entries in snapshots.items()],
        )
        args = {"start_time": "2026-08-08 18:00:00", "end_time": "2026-08-08 20:00:00",
                "source_sat": "S", "check_terminal_node": True}
        with patch.object(handlers, "_connect", return_value=nullcontext(connection)):
            early = handlers.topology_query({**args, "observation_bdt": "2026-08-08 18:05:00"})
            has_child = handlers.topology_query({**args, "observation_bdt": "2026-08-08 18:15:00"})
            no_feeder = handlers.topology_query({**args, "observation_bdt": "2026-08-08 18:35:00"})
            hop_check = handlers.route_path_diagnosis({
                **args,
                "source_sat": "D",
                "affected_objects": [],
                "observation_bdt": "2026-08-08 18:15:00",
            })
        self.assertEqual("yes", early["outcome"])
        self.assertEqual(["S", "N", "L"], early["data"][0]["actual_landing_route"])
        self.assertEqual("no", has_child["outcome"])
        self.assertEqual(["D"], has_child["data"][0]["routed_via_by_satellites"])
        self.assertEqual("no", no_feeder["outcome"])
        self.assertEqual("checked", hop_check["outcome"])
        self.assertTrue(all(row["state"] == "normal" for row in hop_check["data"]))

    def test_explicitly_unavailable_evidence_has_deterministic_tree_behavior(self):
        h2 = handlers.SBC_telemetry_query({
            "tree_node_id": "H2",
            "start_time": "2026-08-08 18:00:00",
            "end_time": "2026-08-08 18:10:00",
        })
        capture = handlers.packet_capture({
            "start_time": "2026-08-08 18:00:00",
            "end_time": "2026-08-08 18:10:00",
        })
        self.assertEqual("not_received", h2["outcome"])
        self.assertIn("无延时遥测", h2["missing_evidence"])
        self.assertEqual("missing_data", capture["status"])
        self.assertIn("不能替代", capture["reason"])

    def test_route_query_keeps_half_hour_samples_and_never_uses_future_state(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("""CREATE TABLE onboard_routing_table_snapshot(
            snapshot_id INTEGER, satellite_id TEXT, queried_bdt TEXT, entries_json TEXT)""")
        entry = {"destination_satellite_id": "A0102", "reachable": True, "hop_count": 1}
        connection.executemany(
            "INSERT INTO onboard_routing_table_snapshot VALUES (?, ?, ?, ?)",
            [(1, "A0101", "2026-08-08 17:00:00.000", json.dumps([entry])),
             (2, "A0101", "2026-08-08 17:30:00.000", "[]")],
        )
        args = {"start_time": "2026-08-08 17:20:00", "end_time": "2026-08-08 17:40:00", "source_sat": "A0101"}
        with patch.object(handlers, "_connect", return_value=nullcontext(connection)):
            before = handlers.route_table_query({**args, "observation_bdt": "2026-08-08 17:25:00"})
            during = handlers.route_table_query(args)
        self.assertEqual(1500, before["data"][0]["sample_age_seconds"])
        self.assertEqual(1, before["data"][0]["total_entry_count"])
        self.assertEqual("2026-08-08 17:30:00.000", during["data"][0]["queried_bdt"])
        self.assertEqual(0, during["data"][0]["total_entry_count"])

    def test_landing_query_pairs_update_ids_without_future_receipts(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("""CREATE TABLE landing_table_update_observation(
            observation_id INTEGER, update_id TEXT, attempt_no INTEGER,
            event_type TEXT, observed_bdt TEXT,
            landing_satellite_id TEXT, gateway_id TEXT, candidate_ids_json TEXT)""")
        connection.executemany(
            "INSERT INTO landing_table_update_observation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(1, "u1", 1, "uplink", "2026-08-08 18:00:00.000", "A0101", "TJS", "[1]"),
             (2, "u1", 1, "receipt_diffusion", "2026-08-08 18:00:01.000", "A0101", "TJS", "[1]"),
             (3, "u2", 1, "uplink", "2026-08-08 19:00:00.000", "A0101", "TJS", "[2]"),
             (4, "u2", 2, "uplink", "2026-08-08 19:00:03.000", "A0101", "TJS", "[2]")],
        )
        args = {"start_time": "2026-08-08 18:00:00", "end_time": "2026-08-08 20:00:00", "landing_satellite_id": "A0101"}
        with patch.object(handlers, "_connect", return_value=nullcontext(connection)):
            result = handlers.landing_table_query(args)
            early = handlers.landing_table_query({**args, "end_time": "2026-08-08 18:00:00.500"})
        self.assertTrue(result["updates"][0]["receipt_diffusion_observed"])
        self.assertFalse(result["updates"][1]["receipt_diffusion_observed"])
        self.assertEqual(2, result["updates"][1]["uplink_attempt_count"])
        self.assertEqual(1, result["updates"][0]["receipt_attempt_no"])
        self.assertFalse(early["updates"][0]["receipt_diffusion_observed"])
        self.assertEqual([1], early["data"][0]["candidate_ids"])

    def test_exact_groups_expand_neighbors_without_merging_contained_events(self):
        events = [
            {
                "satellite_id": satellite,
                "interruption_start_bdt": start,
                "interruption_end_bdt": end,
            }
            for satellite, start, end in (
                ("A0101", "2026-08-08 17:00:00", "2026-08-08 20:00:00"),
                ("A0102", "2026-08-08 18:00:00", "2026-08-08 19:00:00"),
                ("A0104", "2026-08-08 18:00:00.000", "2026-08-08 19:00:00.000"),
                ("A0103", "2026-08-08 18:00:00", "2026-08-08 19:00:00"),
                ("A0105", "2026-08-08 18:00:00.001", "2026-08-08 19:00:00"),
            )
        ]
        groups = group_interruptions(
            events, {"A0102": {"A0104"}, "A0104": {"A0102", "A0103"}}
        )
        self.assertEqual(3, len(groups))
        self.assertEqual(["A0101"], groups[0]["satellites"])
        self.assertEqual(["A0102", "A0104", "A0103"], groups[1]["investigation_order"])
        self.assertEqual(["A0105"], groups[2]["satellites"])

    def test_packetin_tolerance_is_inclusive_and_uses_occurrence(self):
        events = [
            {
                "packetin_id": 1,
                "event_type": "LINK_DOWN",
                "affected_link": "A0101->A0102",
                "occurred_bdt": "2026-08-08 18:00:04.500",
                "received_bdt": "2026-08-08 18:10:00.000",
            },
            {
                "packetin_id": 2,
                "event_type": "LINK_UP",
                "affected_link": "A0101->A0102",
                "occurred_bdt": "2026-08-08 19:00:04.500",
            },
        ]
        def match():
            return match_packetin_boundaries(
                events, "2026-08-08 18:00:00", "2026-08-08 19:00:00"
            )
        self.assertTrue(match()["matched"])
        events[1]["occurred_bdt"] = "2026-08-08 19:00:04.501"
        self.assertFalse(match()["matched"])
        events[1]["occurred_bdt"] = "2026-08-08 19:00:00"
        events[1]["affected_link"] = "A0103->A0104"
        self.assertFalse(match()["matched"])
        events[1]["affected_link"] = "A0101->A0102"
        events[1]["event_type"] = "ROUTE_RECOVER"
        self.assertFalse(match()["matched"])

    def test_packetin_query_expands_window_and_does_not_filter_by_relay_reporter(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE packetin_message (
                packetin_id INTEGER, message_sequence INTEGER, event_type TEXT,
                affected_link TEXT, occurred_bdt TEXT, received_bdt TEXT,
                reporting_satellite_id TEXT)"""
        )
        connection.executemany(
            "INSERT INTO packetin_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 1, "LINK_DOWN", "A0101->A0102", "2026-08-08 18:00:04.500", "2026-08-08 18:10:00.000", "A0601"),
                (2, 2, "LINK_UP", "A0101->A0102", "2026-08-08 19:00:04.500", "2026-08-08 19:10:00.000", "A0601"),
            ],
        )
        args = {
            "start_time": "2026-08-08 18:00:00",
            "end_time": "2026-08-08 19:00:00",
            "interruption_start_bdt": "2026-08-08 18:00:00",
            "interruption_end_bdt": "2026-08-08 19:00:00",
            "affected_link": "A0101->A0102",
            "source_sat": "A0101",
        }
        with patch.object(handlers, "_connect", return_value=nullcontext(connection)):
            result = handlers.packetin_query(args)
            self.assertTrue(result["boundary_match"]["matched"])
            truncated = handlers.packetin_query({**args, "limit": 1})
            self.assertEqual("incomplete", truncated["matching_status"])
            self.assertNotIn("boundary_match", truncated)
            del args["affected_link"]
            with self.assertRaisesRegex(ValueError, "affected_link"):
                handlers.packetin_query(args)

    def test_keepalive_query_does_not_depend_on_continuity_statistics(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """CREATE TABLE keepalive_statistics (
                keepalive_id INTEGER, satellite_id TEXT,
                keepalive_start_bdt TEXT, keepalive_end_bdt TEXT);
               CREATE TABLE v_keepalive_interruptions (
                satellite_id TEXT, interruption_start_bdt TEXT,
                interruption_end_bdt TEXT, interruption_seconds REAL);
               INSERT INTO v_keepalive_interruptions VALUES
                ('A0101', '2026-08-08 17:00:00.000', '2026-08-08 20:00:00.000', 10800),
                ('A0102', '2026-08-08 18:00:00.000', '2026-08-08 19:00:00.000', 3600);"""
        )
        with patch.object(handlers, "_connect", return_value=nullcontext(connection)):
            result = handlers.keep_alive_query({
                "start_time": "2026-08-08 18:10:00",
                "end_time": "2026-08-08 18:20:00",
            })
        self.assertTrue(result["anomaly"])
        self.assertEqual(2, len(result["interruption_groups"]))
        self.assertEqual("2026-08-08 17:00:00.000", result["interruption_groups"][0]["interruption_start_bdt"])


if __name__ == "__main__":
    unittest.main()
