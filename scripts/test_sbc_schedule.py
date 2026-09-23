"""Tests for the deterministic ground-station tracking plan."""

import unittest

from sbc_orbit import generate_passes
from sbc_schedule import (
    TrackingArc,
    build_tracking_plan,
    generate_tracking_plan,
    verify_tracking_plan,
)


def p(sat, gw, start, end, peak_el=45.0):
    from sbc_orbit import SatellitePass

    return SatellitePass(sat, gw, start, end, (start + end) // 2, peak_el, 1)


class TrackingPlanTests(unittest.TestCase):
    def test_real_plan_satisfies_all_constraints(self):
        arcs = generate_tracking_plan()
        self.assertTrue(arcs)
        verify_tracking_plan(arcs)
        # Deterministic
        self.assertEqual([a.arc_id for a in arcs],
                         [a.arc_id for a in generate_tracking_plan()])

    def test_station_never_double_booked(self):
        arcs = generate_tracking_plan()
        for gw in {a.gateway_id for a in arcs}:
            group = sorted((a for a in arcs if a.gateway_id == gw),
                           key=lambda a: a.start_ms)
            for prev, cur in zip(group, group[1:]):
                self.assertLessEqual(prev.end_ms, cur.start_ms, gw)

    def test_satellite_never_tracked_by_two_stations_at_once(self):
        arcs = generate_tracking_plan()
        for sat in {a.satellite_id for a in arcs}:
            group = sorted((a for a in arcs if a.satellite_id == sat),
                           key=lambda a: a.start_ms)
            for prev, cur in zip(group, group[1:]):
                self.assertLessEqual(prev.end_ms, cur.start_ms, sat)

    def test_no_preemption_full_arc_occupancy(self):
        # Continuity-first: the chain starts with the earliest available pass
        # (A0101 at t=0) and occupies its full window; the overlapping later
        # pass (A0102) conflicts on the station and is rejected. No preemption,
        # no mid-arc handover.
        passes = [
            p("A0101", "TJS", 0, 10000, 50.0),
            p("A0102", "TJS", 5000, 15000, 80.0),
        ]
        arcs = build_tracking_plan(passes)
        self.assertEqual([a.satellite_id for a in arcs], ["A0101"])
        self.assertEqual((arcs[0].start_ms, arcs[0].end_ms), (0, 10000))

    def test_satellite_mutex_blocks_second_station(self):
        passes = [
            p("A0101", "TJS", 0, 10000, 50.0),
            p("A0101", "GZS", 4000, 12000, 70.0),
        ]
        arcs = build_tracking_plan(passes)
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0].gateway_id, "TJS")

    def test_back_to_back_arcs_allowed_and_no_handover_within_arc(self):
        passes = [
            p("A0101", "TJS", 0, 5000, 50.0),
            p("A0102", "TJS", 5000, 9000, 60.0),
        ]
        arcs = build_tracking_plan(passes)
        self.assertEqual([a.satellite_id for a in arcs], ["A0101", "A0102"])
        # Each accepted arc keeps its full window (handover only at boundary).
        self.assertEqual((arcs[0].start_ms, arcs[0].end_ms), (0, 5000))
        self.assertEqual((arcs[1].start_ms, arcs[1].end_ms), (5000, 9000))

    def test_overlapping_same_station_only_one_selected(self):
        # Two passes at the same station overlap in time; single-resource
        # constraint means only one can be tracked (no mid-arc handover).
        passes = [
            p("A0102", "TJS", 1000, 6000, 40.0),
            p("A0101", "TJS", 1000, 6000, 80.0),
        ]
        arcs = build_tracking_plan(passes)
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0].gateway_id, "TJS")
        self.assertEqual((arcs[0].start_ms, arcs[0].end_ms), (1000, 6000))

    def test_full_day_plan_keeps_network_always_landed(self):
        # Primary objective: the network always has at least one active feeder
        # arc (so every satellite can land via the mesh), AND no network-wide
        # gap occurs during the A0603 isolation window from a relay that
        # cannot forward (A0603 itself).
        arcs = generate_tracking_plan()
        events = sorted({0, 86400000} | {a.start_ms for a in arcs} | {a.end_ms for a in arcs})
        for start, end in zip(events, events[1:]):
            self.assertTrue(
                any(a.start_ms <= start < a.end_ms for a in arcs),
                f"network-wide outage at {start}",
            )
        iso_start, iso_end = 12 * 3600 * 1000, 15 * 3600 * 1000
        for start, end in zip(events, events[1:]):
            if end <= iso_start or start >= iso_end:
                continue
            self.assertTrue(
                any(a.start_ms <= start < a.end_ms and a.satellite_id != "A0603"
                    for a in arcs),
                f"isolation window lacks a non-isolated relay at {start}",
            )

    def test_network_outages_only_when_no_compatible_pass(self):
        # Residual network-wide gaps must be genuine dead-locks: at a gap
        # instant every geometrically-visible pass conflicts with an accepted
        # arc on its station or satellite (single-resource, full-arc occupancy).
        from sbc_orbit import generate_passes
        arcs = generate_tracking_plan()
        passes = generate_passes()
        events = sorted({0, 86400000} | {a.start_ms for a in arcs} | {a.end_ms for a in arcs})
        for start, end in zip(events, events[1:]):
            if any(a.start_ms <= start < a.end_ms for a in arcs):
                continue
            mid = (start + end) / 2
            for p in passes:
                if p.start_ms <= mid < p.end_ms:
                    station_conflict = any(
                        a.gateway_id == p.gateway_id
                        and a.start_ms < p.end_ms and p.start_ms < a.end_ms for a in arcs)
                    satellite_conflict = any(
                        a.satellite_id == p.satellite_id
                        and a.start_ms < p.end_ms and p.start_ms < a.end_ms for a in arcs)
                    self.assertTrue(
                        station_conflict or satellite_conflict,
                        f"usable pass {p.satellite_id}-{p.gateway_id} at {start} not scheduled",
                    )

    def test_verify_rejects_double_booking(self):
        arcs = [
            TrackingArc("ARC-0001", "A0101", "TJS", 0, 5000, 2500, 50.0, 1),
            TrackingArc("ARC-0002", "A0102", "TJS", 4000, 9000, 6000, 60.0, 1),
        ]
        with self.assertRaises(ValueError):
            verify_tracking_plan(arcs)

    def test_real_plan_stats_reasonable(self):
        passes = generate_passes()
        arcs = generate_tracking_plan()
        # Every station gets some arcs; far fewer than raw passes due to mutex.
        for gw in {p.gateway_id for p in passes}:
            self.assertTrue(any(a.gateway_id == gw for a in arcs), gw)
        self.assertLess(len(arcs), len(passes))


if __name__ == "__main__":
    unittest.main()
