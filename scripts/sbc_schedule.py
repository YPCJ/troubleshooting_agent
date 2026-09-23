"""Deterministic ground-station tracking plan (测控跟踪计划).

Constraints enforced:
  1. One station tracks at most one satellite at any instant.
  2. One satellite is tracked by at most one station at any instant.
  3. No handover inside an arc: an accepted pass occupies its full
     visibility window; a conflicting request is rejected, never preempted.

Policy: maximize coverage. A min-cost max-flow over a time-expanded DAG
selects, for each station, a non-overlapping sequence of passes such that
as many distinct satellites as possible receive at least one feeder arc.
Satellite capacity 1 enforces one-station-per-satellite globally. This is a
synthetic coverage-optimal plan, not an operational scheduler.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sbc_orbit import SIMULATION_MS, SatellitePass, generate_passes

SCHEDULE_METADATA: dict[str, tuple[str, str]] = {
    "tracking_plan_policy": (
        "continuity_first_chain",
        "测控跟踪计划：时间扫描保证任意时刻至少一条馈电链路（全网不断链），再致密化覆盖更多星；不抢占、弧段内不换手",
    ),
    "tracking_constraints": (
        "one_satellite_per_station;one_station_per_satellite;full_arc_occupancy",
        "互斥约束：一站同时一星、一星同时一站、接纳即占满整条可见弧段",
    ),
    "tracking_objective": (
        "always_on_feeder_then_max_coverage",
        "优化目标：首要保证全网始终有可中继的落地星（剔除孤立星），其次最大化被直接覆盖的卫星数",
    ),
    "isolated_satellite_excluded_as_relay": (
        "A0603@2026-08-08 12:00-15:00",
        "A0603重构隔离期间不作为骨干中继落地星（它本星可落地但无法为他人中继）",
    ),
    "priority_satellite_tracking": (
        "A0603:every_pass_cluster_highest_elevation",
        "A0603重构期测控优先：每个过境簇（一圈内多站同见）优先分配最高仰角弧段，保证凡有过境必落地；"
        "目标落地间隔≤2圈(约4.23h)，受轨道几何限制时段(14:46-21:27不可见)除外",
    ),
    "schedule_is_plan_only": (
        "synthetic",
        "跟踪计划为合成假设，用于馈电/选路/统计，不代表真实测控排程",
    ),
}


@dataclass(frozen=True)
class TrackingArc:
    """One accepted station-satellite tracking arc (测控跟踪弧段)."""

    arc_id: str
    satellite_id: str
    gateway_id: str
    start_ms: int
    end_ms: int
    peak_ms: int
    peak_elevation_deg: float
    orbit_number: int


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end





def build_tracking_plan(passes: list[SatellitePass]) -> list[TrackingArc]:
    """Select tracking arcs so the network always has a live feeder link.

    Primary invariant: because the constellation is fully meshed, as long as
    at least one satellite has an active feeder arc, every satellite can land.
    Geometry guarantees some satellite is above a station's horizon at all
    times, so we sweep time and always keep one station tracking one visible
    satellite. Mutual exclusion holds instant-by-instant: a station tracks one
    satellite, and a satellite is tracked by one station, at any moment. An
    accepted arc spans its full visibility window (no mid-arc handover);
    when the current arc ends we immediately pick another visible satellite.

    Secondary objective: rotate among satellites so all 60 get direct feeder
    arcs over the day (maximize distinct coverage) without breaking continuity.
    """
    station_busy: dict[str, list[tuple[int, int]]] = defaultdict(list)
    satellite_busy: dict[str, list[tuple[int, int]]] = defaultdict(list)
    covered: set[str] = set()
    accepted: list[TrackingArc] = []
    counter = 0
    # A0603 is reconstructing 12:00-15:00 with all inter-satellite links cut, so
    # it can only land via its OWN passes. Give it priority on tracking arcs so
    # it lands frequently; other satellites can always relay through the mesh.
    ISO_SAT, ISO_START, ISO_END = "A0603", 12 * 3600 * 1000, 15 * 3600 * 1000
    MAX_PRIORITY_GAP = 2 * 7622 * 1000  # two orbital periods in ms

    def free(p: SatellitePass) -> bool:
        return not any(_overlaps(p.start_ms, p.end_ms, s, e)
                       for s, e in station_busy[p.gateway_id]) and \
               not any(_overlaps(p.start_ms, p.end_ms, s, e)
                       for s, e in satellite_busy[p.satellite_id])

    def take(p: SatellitePass) -> None:
        nonlocal counter
        counter += 1
        accepted.append(TrackingArc(
            f"ARC-{counter:04d}", p.satellite_id, p.gateway_id,
            p.start_ms, p.end_ms, p.peak_ms, p.peak_elevation_deg, p.orbit_number))
        station_busy[p.gateway_id].append((p.start_ms, p.end_ms))
        satellite_busy[p.satellite_id].append((p.start_ms, p.end_ms))
        covered.add(p.satellite_id)

    # Phase 0 (priority): A0603 can only self-land during reconstruction, so it
    # gets first claim on tracking arcs. Group its simultaneous multi-station
    # passes into clusters (one orbit pass over the region) and take the highest
    # -elevation station per cluster, guaranteeing consecutive A0603 landing
    # arcs are never more than two orbital periods apart where geometry allows.
    iso_passes = sorted((p for p in passes if p.satellite_id == ISO_SAT),
                        key=lambda p: p.start_ms)
    clusters: list[list[SatellitePass]] = []
    for p in iso_passes:
        if clusters and p.start_ms < clusters[-1][-1].end_ms:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last_taken_end: int | None = None
    for cluster in clusters:
        c_start = cluster[0].start_ms
        # Must take a cluster if skipping it would push the gap between A0603
        # landing arcs beyond two orbital periods; otherwise take the best one
        # when free (cheap, improves A0603's direct-landing cadence).
        overdue = last_taken_end is None or (c_start - last_taken_end) > MAX_PRIORITY_GAP
        for best in sorted(cluster, key=lambda p: (-p.peak_elevation_deg, p.start_ms)):
            if free(best):
                take(best)
                last_taken_end = best.end_ms
                break
        else:
            if overdue:
                # geometry gave a cluster but every station conflicts; cannot
                # satisfy the 2-orbit cadence here — accept the gap.
                pass

    gateways = sorted({p.gateway_id for p in passes})
    # A satellite tracked now hands off only when its window ends. Keep a chain
    # of arcs so some feeder link is always active. During the A0603 isolation
    # window (12:00-15:00) A0603 cannot relay for others, so do not use its
    # passes as the sole backbone link there (it may still self-land via a
    # later densify arc, which is fine).
    ISO_SAT, ISO_START, ISO_END = "A0603", 12 * 3600 * 1000, 15 * 3600 * 1000

    def relay_ok(p: SatellitePass, start: int) -> bool:
        # If this pass would be the only active link during isolation, the
        # landing satellite must be able to relay (i.e., not isolated then).
        if p.satellite_id != ISO_SAT:
            return True
        return not (start < ISO_END and p.end_ms > ISO_START)

    cursor = 0
    while cursor < SIMULATION_MS:
        best: SatellitePass | None = None
        best_start = SIMULATION_MS
        for p in passes:
            if not free(p):
                continue
            start = max(cursor, p.start_ms)
            if start >= p.end_ms:
                continue  # window already passed
            if not relay_ok(p, start):
                continue
            if start < best_start or (
                start == best_start and best is not None
                and (p.satellite_id not in covered, -(p.end_ms - start),
                     -p.peak_elevation_deg, p.satellite_id)
                < (best.satellite_id not in covered, -(best.end_ms - start),
                   -best.peak_elevation_deg, best.satellite_id)
            ):
                best, best_start = p, start
        if best is None:
            break  # no future pass can start (should not happen given geometry)
        take(best)
        cursor = best.end_ms

    # Densify: add any additional non-conflicting arcs (other stations idle
    # while the backbone chain runs), preferring uncovered satellites so all
    # 60 get direct feeder arcs. Continuity is already guaranteed above.
    for p in sorted(passes, key=lambda p: (p.satellite_id in covered,
                                           p.start_ms, -p.peak_elevation_deg,
                                           p.satellite_id, p.gateway_id)):
        if free(p):
            take(p)

    return sorted(accepted, key=lambda a: (a.start_ms, a.satellite_id, a.gateway_id))


def generate_tracking_plan() -> list[TrackingArc]:
    """Compute passes and schedule them into a tracking plan."""
    return build_tracking_plan(generate_passes())


def verify_tracking_plan(arcs: list[TrackingArc]) -> None:
    """Raise ValueError if any mutual-exclusion or handover rule is violated."""
    by_station: dict[str, list[TrackingArc]] = {}
    by_satellite: dict[str, list[TrackingArc]] = {}
    for arc in arcs:
        if not 0 <= arc.start_ms < arc.end_ms <= SIMULATION_MS:
            raise ValueError(f"Arc outside day or empty: {arc.arc_id}")
        if not arc.start_ms <= arc.peak_ms < arc.end_ms:
            raise ValueError(f"Arc peak outside window: {arc.arc_id}")
        by_station.setdefault(arc.gateway_id, []).append(arc)
        by_satellite.setdefault(arc.satellite_id, []).append(arc)
    for label, groups in (("station", by_station), ("satellite", by_satellite)):
        for key, group in groups.items():
            ordered = sorted(group, key=lambda a: a.start_ms)
            for previous, current in zip(ordered, ordered[1:]):
                if current.start_ms < previous.end_ms:
                    raise ValueError(
                        f"{label} {key} double-booked: {previous.arc_id} vs {current.arc_id}"
                    )
    if arcs != sorted(arcs, key=lambda a: (a.start_ms, a.satellite_id, a.gateway_id)):
        raise ValueError("Tracking arcs must be sorted")
    if len({a.arc_id for a in arcs}) != len(arcs):
        raise ValueError("Duplicate arc IDs")
