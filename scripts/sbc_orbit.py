"""Deterministic, synthetic circular-orbit visibility (stdlib only).

Times are elapsed SI seconds from 2026-08-08 00:00:00.000 BDT, not Unix
timestamps. Greenwich's inertial angle is DEFINED to be zero at that epoch;
this is not actual GMST and requires no BDT/UTC conversion. Earth is spherical,
stations have zero height, and there is no precession, oblateness, refraction,
terrain, light-time correction, or interplane phasing.

Pass intervals are half-open integer milliseconds, clipped to one day.
Rising crossings round up and setting crossings round down. The peak is the
best integer millisecond in that stored interval, not an unrounded timestamp.
Orbit numbers are one-based satellite revolutions at the stored peak, including
the satellite's initial slot anomaly; they are not global elapsed-day counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, ceil, cos, degrees, floor, isfinite, pi, radians, sin, sqrt


EARTH_RADIUS_KM = 6371.0
EARTH_MU_KM3_S2 = 398600.4418
ORBIT_ALTITUDE_KM = 2000.0
ORBIT_RADIUS_KM = EARTH_RADIUS_KM + ORBIT_ALTITUDE_KM
INCLINATION_DEG = 88.0
EARTH_ROTATION_RAD_S = 7.2921150e-5
MIN_ELEVATION_DEG = 10.0
SIMULATION_SECONDS = 86400.0
SIMULATION_MS = 86400000
ORBIT_PERIOD_SECONDS = 2.0 * pi * sqrt(ORBIT_RADIUS_KM**3 / EARTH_MU_KM3_S2)
MEAN_MOTION_RAD_S = 2.0 * pi / ORBIT_PERIOD_SECONDS
STATIONS: dict[str, tuple[float, float]] = {
    "TJS": (39.05, 115.98),
    "GZS": (23.13, 113.26),
    "CDS": (29.56, 106.55),
}
SATELLITE_IDS = tuple(
    f"A{plane:02d}{slot:02d}" for plane in range(1, 7) for slot in range(1, 11)
)
MODEL_METADATA: dict[str, tuple[str, str]] = {
    "orbit_model": ("spherical_earth_circular_orbit", "球形地球、二体圆轨道合成模型"),
    "simulation_epoch_bdt": ("2026-08-08 00:00:00.000", "仿真起始北斗时间；输入为此后经过的秒数"),
    "simulation_duration_seconds": ("86400", "仿真持续秒数；时间窗采用左闭右开区间"),
    "earth_radius_km": (str(EARTH_RADIUS_KM), "球形地球半径（千米）"),
    "earth_mu_km3_s2": (str(EARTH_MU_KM3_S2), "地球标准引力参数（千米三次方每秒平方）"),
    "orbit_altitude_km": (str(ORBIT_ALTITUDE_KM), "圆轨道高度（千米）"),
    "orbit_inclination_deg": (str(INCLINATION_DEG), "轨道倾角（度）"),
    "orbit_period_seconds": (str(ORBIT_PERIOD_SECONDS), "圆轨道周期（秒）"),
    "raan_deg": ("(plane-1)*60", "六个轨道面的升交点赤经（度）"),
    "initial_anomaly_deg": ("(slot-1)*36", "每面十颗卫星初始相位（度）；轨道面间无相位偏移"),
    "earth_rotation_rad_s": (str(EARTH_ROTATION_RAD_S), "地球自转角速度（弧度每秒）"),
    "greenwich_angle_at_epoch_rad": ("0", "合成历元格林尼治角定义为零，非真实恒星时；无需北斗时与UTC换算"),
    "station_coordinates_deg": ("TJS:39.05,115.98;GZS:23.13,113.26;CDS:29.56,106.55", "近似站点纬度、东经（度）；球面高程为零"),
    "minimum_elevation_deg": (str(MIN_ELEVATION_DEG), "星地可见最低仰角（度）"),
    "visibility_solver": ("60s_derivative_mesh;extrema_refinement;1e-8s_root_brackets", "解析导数极值搜索及数值精化；曲率界保证捕获无可见网格采样点的擦边过站"),
    "crossing_rounding": ("start=ceil(ms);end=floor(ms)", "起点向上、终点向下取整毫秒，保守向内裁剪"),
    "orbit_number": ("1+floor((initial_anomaly+mean_motion*peak_seconds)/(2*pi))", "峰值时刻含初始相位的卫星圈号，从1开始"),
    "limitations": ("no_J2_precession_refraction_terrain_light_time", "不含摄动、折射、地形遮挡和光行时；用于合成数据而非真实轨道预报"),
}

_STEP_SECONDS = 60.0
_ROOT_TOLERANCE_SECONDS = 1e-8
_COS_INCLINATION = cos(radians(INCLINATION_DEG))
_SIN_INCLINATION = sin(radians(INCLINATION_DEG))
_MIN_ELEVATION_RAD = radians(MIN_ELEVATION_DEG)
_RADIUS_RATIO = EARTH_RADIUS_KM / ORBIT_RADIUS_KM
_VISIBILITY_DOT = (
    _RADIUS_RATIO * cos(_MIN_ELEVATION_RAD) ** 2
    + sin(_MIN_ELEVATION_RAD)
    * sqrt(1.0 - (_RADIUS_RATIO * cos(_MIN_ELEVATION_RAD)) ** 2)
)


@dataclass(frozen=True)
class SatellitePass:
    satellite_id: str
    gateway_id: str
    start_ms: int
    end_ms: int
    peak_ms: int
    peak_elevation_deg: float
    orbit_number: int


def _phase(satellite_id: str) -> tuple[float, float]:
    if satellite_id not in SATELLITE_IDS:
        raise ValueError(f"Unknown satellite ID: {satellite_id!r}")
    return radians((int(satellite_id[1:3]) - 1) * 60), radians(
        (int(satellite_id[3:5]) - 1) * 36
    )


def _check_seconds(seconds: float) -> None:
    if not isfinite(seconds):
        raise ValueError("Elapsed seconds must be finite")


def _station(gateway_id: str) -> tuple[float, float]:
    try:
        latitude, longitude = STATIONS[gateway_id]
    except KeyError:
        raise ValueError(f"Unknown gateway ID: {gateway_id!r}") from None
    return radians(latitude), radians(longitude)


def satellite_position(
    satellite_id: str, seconds: float
) -> tuple[float, float, float]:
    """Return ECEF kilometres; finite times outside the simulation are allowed."""
    raan, initial_anomaly = _phase(satellite_id)
    _check_seconds(seconds)
    anomaly = initial_anomaly + MEAN_MOTION_RAD_S * seconds
    node = raan - EARTH_ROTATION_RAD_S * seconds
    x = cos(node) * cos(anomaly) - sin(node) * sin(anomaly) * _COS_INCLINATION
    y = sin(node) * cos(anomaly) + cos(node) * sin(anomaly) * _COS_INCLINATION
    z = sin(anomaly) * _SIN_INCLINATION
    return ORBIT_RADIUS_KM * x, ORBIT_RADIUS_KM * y, ORBIT_RADIUS_KM * z


def _dot_and_rate(
    raan: float, initial_anomaly: float, latitude: float, longitude: float, seconds: float
) -> tuple[float, float]:
    """Unit geocentric station/satellite dot product and its time derivative."""
    anomaly = initial_anomaly + MEAN_MOTION_RAD_S * seconds
    node = raan - longitude - EARTH_ROTATION_RAD_S * seconds
    ca, sa, cn, sn = cos(anomaly), sin(anomaly), cos(node), sin(node)
    cl, sl = cos(latitude), sin(latitude)
    dot = cl * (cn * ca - sn * sa * _COS_INCLINATION) + sl * sa * _SIN_INCLINATION
    rate = cl * (
        EARTH_ROTATION_RAD_S * (sn * ca + cn * sa * _COS_INCLINATION)
        - MEAN_MOTION_RAD_S * (cn * sa + sn * ca * _COS_INCLINATION)
    ) + sl * MEAN_MOTION_RAD_S * ca * _SIN_INCLINATION
    return dot, rate


def _elevation_from_dot(dot: float) -> float:
    distance = sqrt(
        ORBIT_RADIUS_KM**2 + EARTH_RADIUS_KM**2
        - 2.0 * ORBIT_RADIUS_KM * EARTH_RADIUS_KM * dot
    )
    return degrees(asin(max(-1.0, min(1.0, (ORBIT_RADIUS_KM * dot - EARTH_RADIUS_KM) / distance))))


def elevation_deg(satellite_id: str, gateway_id: str, seconds: float) -> float:
    """Geometric elevation above the spherical station's local horizon."""
    raan, initial_anomaly = _phase(satellite_id)
    latitude, longitude = _station(gateway_id)
    _check_seconds(seconds)
    dot, _ = _dot_and_rate(raan, initial_anomaly, latitude, longitude, seconds)
    return _elevation_from_dot(dot)


def _bisect(function, left: float, right: float) -> tuple[float, float]:
    """Preserve a sign-changing bracket, including an exactly sampled root."""
    left_value = function(left)
    if left_value == 0:
        return left, left
    if function(right) == 0:
        return right, right
    while right - left > _ROOT_TOLERANCE_SECONDS:
        middle = (left + right) / 2.0
        value = function(middle)
        if value == 0:
            return middle, middle
        if (value > 0) == (left_value > 0):
            left, left_value = middle, value
        else:
            right = middle
    return left, right


def _orbit_number(satellite_id: str, peak_ms: int) -> int:
    _, phase = _phase(satellite_id)
    return 1 + floor((phase + MEAN_MOTION_RAD_S * peak_ms / 1000.0) / (2.0 * pi))


def _pair_passes(satellite_id: str, gateway_id: str) -> list[SatellitePass]:
    raan, anomaly = _phase(satellite_id)
    latitude, longitude = _station(gateway_id)

    def geometry(seconds: float) -> tuple[float, float]:
        return _dot_and_rate(raan, anomaly, latitude, longitude, seconds)

    def margin(seconds: float) -> float:
        return geometry(seconds)[0] - _VISIBILITY_DOT

    def rate(seconds: float) -> float:
        return geometry(seconds)[1]

    # f'' <= -n²*f + 2*n*w + w², and |f'| <= n+w. Thus f is
    # strictly concave throughout both mesh neighbours of ANY visible maximum.
    # This inequality guarantees a + to - derivative bracket even for a grazing
    # pass with no visible grid samples. Do not replace this with a positive-
    # sample-only crossing search or increase the mesh without this check.
    n, w = MEAN_MOTION_RAD_S, EARTH_ROTATION_RAD_S
    if _VISIBILITY_DOT - (n + w) * _STEP_SECONDS <= (2 * n * w + w * w) / (n * n):
        raise ValueError("Extrema mesh is too wide for guaranteed grazing-pass detection")

    times = [
        min(index * _STEP_SECONDS, SIMULATION_SECONDS)
        for index in range(ceil(SIMULATION_SECONDS / _STEP_SECONDS) + 1)
    ]
    samples = [(time, *geometry(time)) for time in times]
    maxima: list[float] = []
    for left, right in zip(samples, samples[1:]):
        if left[2] >= 0 and right[2] <= 0:
            lo, hi = _bisect(rate, left[0], right[0])
            peak = (lo + hi) / 2.0
            if margin(peak) > 0:
                maxima.append(peak)
    nodes = sorted(set(times + maxima))
    windows: list[tuple[float, float]] = []
    start = 0.0 if margin(0.0) >= 0 else None
    for left, right in zip(nodes, nodes[1:]):
        left_visible, right_visible = margin(left) >= 0, margin(right) >= 0
        if not left_visible and right_visible:
            _, start = _bisect(margin, left, right)
        elif left_visible and not right_visible:
            end, _ = _bisect(margin, left, right)
            if start is not None:
                windows.append((start, end))
            start = None
    if start is not None:
        windows.append((start, SIMULATION_SECONDS))

    passes = []
    for start, end in windows:
        start_ms, end_ms = max(0, ceil(start * 1000)), min(SIMULATION_MS, floor(end * 1000))
        if start_ms >= end_ms:
            continue
        # The clipped continuous peak can be at either end of the day.
        candidates = [start_ms, end_ms - 1]
        for peak in maxima:
            if start <= peak <= end:
                candidates.extend(
                    max(start_ms, min(end_ms - 1, ms))
                    for ms in (floor(peak * 1000), ceil(peak * 1000))
                )
        peak_ms = max(candidates, key=lambda ms: (geometry(ms / 1000.0)[0], -ms))
        passes.append(SatellitePass(
            satellite_id, gateway_id, start_ms, end_ms, peak_ms,
            _elevation_from_dot(geometry(peak_ms / 1000.0)[0]),
            _orbit_number(satellite_id, peak_ms),
        ))
    return passes


def generate_passes() -> list[SatellitePass]:
    """Generate all 60 satellites' >=10-degree passes at the three stations."""
    passes = [
        window
        for satellite_id in SATELLITE_IDS
        for gateway_id in STATIONS
        for window in _pair_passes(satellite_id, gateway_id)
    ]
    return sorted(passes, key=lambda window: (window.start_ms, window.satellite_id, window.gateway_id))


def verify_passes(passes: list[SatellitePass]) -> None:
    """Raise ValueError on invalid ordering, clipping, boundaries or geometry.

    Verifies supplied windows, not completeness of the supplied collection.
    An independent coverage scan is provided by the accompanying unit tests.
    """
    if passes != sorted(passes, key=lambda p: (p.start_ms, p.satellite_id, p.gateway_id)):
        raise ValueError("Passes must be sorted by (start_ms, satellite_id, gateway_id)")
    previous_end: dict[tuple[str, str], int] = {}
    tolerance = 1e-8
    for window in passes:
        _phase(window.satellite_id)
        _station(window.gateway_id)
        if any(type(value) is not int for value in (
            window.start_ms, window.end_ms, window.peak_ms, window.orbit_number
        )):
            raise ValueError("Times and orbit number must be integer values")
        if not 0 <= window.start_ms <= window.peak_ms < window.end_ms <= SIMULATION_MS:
            raise ValueError("Pass is empty, improperly clipped, or peak is outside the pass")
        key = window.satellite_id, window.gateway_id
        if window.start_ms < previous_end.get(key, -1):
            raise ValueError("Duplicate or overlapping passes")
        previous_end[key] = window.end_ms
        if window.orbit_number != _orbit_number(window.satellite_id, window.peak_ms):
            raise ValueError("Incorrect orbit number")

        def elevation(ms: int) -> float:
            return elevation_deg(window.satellite_id, window.gateway_id, ms / 1000.0)

        observed_peak = elevation(window.peak_ms)
        if not isfinite(window.peak_elevation_deg) or abs(observed_peak - window.peak_elevation_deg) > tolerance:
            raise ValueError("Peak elevation disagrees with geometry")
        checks = [window.start_ms, window.end_ms - 1, window.end_ms, window.peak_ms]
        checks.extend(range(window.start_ms, window.end_ms, int(_STEP_SECONDS * 1000)))
        if any(elevation(ms) < MIN_ELEVATION_DEG - tolerance for ms in checks):
            raise ValueError("Pass contains an invisible time")
        if any(elevation(ms) > observed_peak + tolerance for ms in checks if ms < window.end_ms):
            raise ValueError("Peak is not the maximum elevation")
        for ms in (window.peak_ms - 1, window.peak_ms + 1):
            if window.start_ms <= ms < window.end_ms and elevation(ms) > observed_peak + tolerance:
                raise ValueError("Peak timestamp is not locally optimal")
        if window.start_ms > 0 and elevation(window.start_ms - 1) > MIN_ELEVATION_DEG + tolerance:
            raise ValueError("Start is not conservatively rounded at the rising crossing")
        if window.end_ms < SIMULATION_MS and elevation(window.end_ms + 1) > MIN_ELEVATION_DEG + tolerance:
            raise ValueError("End is not conservatively rounded at the setting crossing")
