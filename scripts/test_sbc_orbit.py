"""Run with .venv/bin/python -m unittest discover -s scripts -p test_sbc_orbit.py."""

from dataclasses import FrozenInstanceError, replace
from math import acos, asin, atan2, cos, degrees, hypot, pi, radians, sin, sqrt
import unittest
from unittest.mock import patch

try:
    from . import sbc_orbit as orbit
except ImportError:
    import sbc_orbit as orbit


def reference_elevation(satellite_id, coordinates, seconds):
    """Independent ECI station/LOS construction, without production helpers."""
    radius, earth_radius, mu = 8371.0, 6371.0, 398600.4418
    n = sqrt(mu / radius**3)
    node = radians((int(satellite_id[1:3]) - 1) * 60)
    u = radians((int(satellite_id[3:]) - 1) * 36) + n * seconds
    inclination = radians(88)
    satellite = (
        radius * (cos(node) * cos(u) - sin(node) * sin(u) * cos(inclination)),
        radius * (sin(node) * cos(u) + cos(node) * sin(u) * cos(inclination)),
        radius * sin(u) * sin(inclination),
    )
    lat, lon = map(radians, coordinates)
    lon += 7.2921150e-5 * seconds
    zenith = (cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat))
    line = tuple(satellite[i] - earth_radius * zenith[i] for i in range(3))
    return degrees(asin(sum(line[i] * zenith[i] for i in range(3)) / hypot(*line)))


class OrbitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.passes = orbit.generate_passes()
        cls.by_pair = {}
        for window in cls.passes:
            cls.by_pair.setdefault((window.satellite_id, window.gateway_id), []).append(window)

    def test_circular_radius_period_and_phase(self):
        self.assertEqual(len(orbit.SATELLITE_IDS), 60)
        self.assertAlmostEqual(
            orbit.ORBIT_PERIOD_SECONDS, 2 * pi * sqrt(8371.0**3 / 398600.4418), places=10
        )
        for satellite_id in orbit.SATELLITE_IDS:
            initial = orbit.satellite_position(satellite_id, 0)
            for seconds in (0, 1234.5, 86400):
                self.assertAlmostEqual(hypot(*orbit.satellite_position(satellite_id, seconds)), 8371, places=8)
            # An orbital period returns to the same INERTIAL point, not ECEF.
            fixed = orbit.satellite_position(satellite_id, orbit.ORBIT_PERIOD_SECONDS)
            theta = orbit.EARTH_ROTATION_RAD_S * orbit.ORBIT_PERIOD_SECONDS
            inertial = (
                cos(theta) * fixed[0] - sin(theta) * fixed[1],
                sin(theta) * fixed[0] + cos(theta) * fixed[1],
                fixed[2],
            )
            for actual, expected in zip(inertial, initial):
                self.assertAlmostEqual(actual, expected, places=8)
        self.assertEqual(orbit.satellite_position("A0101", 0), (8371.0, 0.0, 0.0))
        for plane in range(1, 7):
            angle = radians((plane - 1) * 60)
            position = orbit.satellite_position(f"A{plane:02d}01", 0)
            self.assertAlmostEqual(position[0], 8371 * cos(angle), places=8)
            self.assertAlmostEqual(position[1], 8371 * sin(angle), places=8)
            self.assertEqual(position[2], 0)
        for slot in range(1, 11):
            phase = radians((slot - 1) * 36)
            position = orbit.satellite_position(f"A01{slot:02d}", 0)
            expected = (
                8371 * cos(phase),
                8371 * sin(phase) * cos(radians(88)),
                8371 * sin(phase) * sin(radians(88)),
            )
            for actual, target in zip(position, expected):
                self.assertAlmostEqual(actual, target, places=8)

    def test_elevation_reference_and_basic_geometry(self):
        for satellite_id in ("A0101", "A0206", "A0610"):
            for gateway_id, coordinates in orbit.STATIONS.items():
                for seconds in (0, 337.25, 12345.678, 86400):
                    self.assertAlmostEqual(
                        orbit.elevation_deg(satellite_id, gateway_id, seconds),
                        reference_elevation(satellite_id, coordinates, seconds),
                        places=9,
                    )
        with patch.dict(orbit.STATIONS, {"ZENITH": (0.0, 0.0), "NADIR": (0.0, 180.0)}):
            self.assertAlmostEqual(orbit.elevation_deg("A0101", "ZENITH", 0), 90)
            self.assertAlmostEqual(orbit.elevation_deg("A0101", "NADIR", 0), -90)
        horizon_lon = degrees(acos(6371.0 / 8371.0))
        with patch.dict(orbit.STATIONS, {"HORIZON": (0.0, horizon_lon)}):
            self.assertAlmostEqual(orbit.elevation_deg("A0101", "HORIZON", 0), 0, places=10)

    def test_clipping_rounding_peaks_and_immutable_records(self):
        self.assertTrue(self.passes)
        self.assertTrue(any(p.start_ms == 0 for p in self.passes))
        self.assertTrue(any(p.end_ms == 86400000 for p in self.passes))
        for window in self.passes:
            self.assertTrue(0 <= window.start_ms <= window.peak_ms < window.end_ms <= 86400000)
            coordinates = orbit.STATIONS[window.gateway_id]

            def elevation(ms):
                return reference_elevation(window.satellite_id, coordinates, ms / 1000)

            self.assertGreaterEqual(elevation(window.start_ms), 10 - 1e-8)
            self.assertGreaterEqual(elevation(window.end_ms), 10 - 1e-8)
            if window.start_ms:
                self.assertLessEqual(elevation(window.start_ms - 1), 10 + 1e-8)
            if window.end_ms < 86400000:
                self.assertLessEqual(elevation(window.end_ms + 1), 10 + 1e-8)
            peak = elevation(window.peak_ms)
            self.assertAlmostEqual(peak, window.peak_elevation_deg, places=8)
            for ms in (window.peak_ms - 1, window.peak_ms + 1):
                if window.start_ms <= ms < window.end_ms:
                    self.assertLessEqual(elevation(ms), peak + 1e-10)
            phase = (int(window.satellite_id[3:]) - 1) / 10
            expected_orbit = 1 + int(phase + window.peak_ms / 1000 / orbit.ORBIT_PERIOD_SECONDS)
            self.assertEqual(window.orbit_number, expected_orbit)
        with self.assertRaises(FrozenInstanceError):
            self.passes[0].start_ms = 1

    def test_determinism_and_verifier(self):
        self.assertEqual(self.passes, orbit.generate_passes())
        orbit.verify_passes(self.passes)
        orbit.verify_passes([])
        with self.assertRaises(ValueError):
            orbit.verify_passes(list(reversed(self.passes)))
        window = next(p for p in self.passes if p.start_ms > 0 and p.end_ms < 86400000)
        for invalid in (
            replace(window, start_ms=-1),
            replace(window, end_ms=window.start_ms),
            replace(window, end_ms=86400001),
            replace(window, peak_ms=window.end_ms),
            replace(window, peak_elevation_deg=float("nan")),
            replace(window, peak_elevation_deg=window.peak_elevation_deg + 1),
            replace(window, orbit_number=window.orbit_number + 1),
            replace(window, start_ms=window.start_ms + 100),
            replace(window, end_ms=window.end_ms - 100),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                orbit.verify_passes([invalid])
        with self.assertRaises(ValueError):
            orbit.verify_passes([window, window])

    def test_independent_dense_scan_coverage(self):
        # 1,555,200 independent ECI samples: every 10 s, all 180 sat/station
        # pairs, including invisible pairs. Boundary tests above check 1 ms.
        for satellite_id in orbit.SATELLITE_IDS:
            for gateway_id, coordinates in orbit.STATIONS.items():
                windows = self.by_pair.get((satellite_id, gateway_id), [])
                index = 0
                for seconds in range(0, 86400, 10):
                    ms = seconds * 1000
                    while index < len(windows) and windows[index].end_ms <= ms:
                        index += 1
                    visible = reference_elevation(satellite_id, coordinates, seconds) >= 10
                    stored = index < len(windows) and windows[index].start_ms <= ms < windows[index].end_ms
                    if visible != stored:
                        # An inward-rounded setting boundary may exclude <1 ms
                        # that is still physically visible.
                        near_setting = any(0 <= ms - p.end_ms <= 1 for p in windows)
                        self.assertTrue(
                            visible and not stored and near_setting,
                            (satellite_id, gateway_id, seconds, visible, stored),
                        )

    def test_grazing_pass_without_any_positive_grid_sample(self):
        seconds = 1234.567
        n, w = sqrt(398600.4418 / 8371.0**3), 7.2921150e-5
        u, theta, inclination = n * seconds, w * seconds, radians(88)
        q = tuple(x / 8371 for x in orbit.satellite_position("A0101", seconds))
        inertial_velocity = (-n * sin(u), n * cos(u) * cos(inclination), n * cos(u) * sin(inclination))
        v = (
            cos(theta) * inertial_velocity[0] + sin(theta) * inertial_velocity[1] + w * q[1],
            -sin(theta) * inertial_velocity[0] + cos(theta) * inertial_velocity[1] - w * q[0],
            inertial_velocity[2],
        )
        normal = (q[1] * v[2] - q[2] * v[1], q[2] * v[0] - q[0] * v[2], q[0] * v[1] - q[1] * v[0])
        length = hypot(*normal)
        # Offset station normal to the apparent trajectory: q' dot station=0.
        # Raise the peak only ~1e-7 degrees above the actual 10-degree mask.
        dot = orbit._VISIBILITY_DOT + 1e-9
        station = tuple(dot * q[i] + sqrt(1 - dot * dot) * normal[i] / length for i in range(3))
        coordinates = (degrees(asin(station[2])), degrees(atan2(station[1], station[0])))
        with patch.dict(orbit.STATIONS, {"TJS": coordinates}):
            windows = orbit._pair_passes("A0101", "TJS")
            grazing = [p for p in windows if p.start_ms <= seconds * 1000 < p.end_ms]
            self.assertEqual(len(grazing), 1)
            window = grazing[0]
            self.assertLess(window.end_ms - window.start_ms, 1000)
            self.assertGreater(window.end_ms - window.start_ms, 1)
            for sample in (1200, 1260):
                self.assertLess(reference_elevation("A0101", coordinates, sample), 10)
            self.assertGreater(reference_elevation("A0101", coordinates, seconds), 10)
            self.assertLessEqual(abs(window.peak_ms - round(seconds * 1000)), 1)
            orbit.verify_passes(windows)
            for ms in range(window.start_ms - 2, window.end_ms + 3):
                visible = reference_elevation("A0101", coordinates, ms / 1000) >= 10
                stored = window.start_ms <= ms < window.end_ms
                if visible != stored:
                    self.assertTrue(visible and ms == window.end_ms)

    def test_input_validation_and_metadata(self):
        for satellite_id in ("A0001", "A0701", "A0111", "A0100", "A101", ""):
            with self.assertRaises(ValueError):
                orbit.satellite_position(satellite_id, 0)
        with self.assertRaises(ValueError):
            orbit.elevation_deg("A0101", "INVALID", 0)
        for seconds in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                orbit.satellite_position("A0101", seconds)
            with self.assertRaises(ValueError):
                orbit.elevation_deg("A0101", "TJS", seconds)
        for value, description in orbit.MODEL_METADATA.values():
            self.assertIsInstance(value, str)
            self.assertIsInstance(description, str)
            self.assertTrue(description)
        self.assertEqual(orbit.MODEL_METADATA["greenwich_angle_at_epoch_rad"][0], "0")


if __name__ == "__main__":
    unittest.main()
