from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Mapping


PACKETIN_TOLERANCE_SECONDS = 4.5


def parse_bdt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("Use BDT without a timezone offset")
    return parsed


def terminal_node_evidence(
    satellite: str,
    actual_landing_routes: Mapping[str, list[str]],
    landing_satellites: set[str],
) -> dict[str, Any]:
    route = actual_landing_routes.get(satellite)
    valid_route = bool(
        route
        and len(route) >= 2
        and route[0] == satellite
        and route[-1] in landing_satellites
    )
    routed_via_by = sorted(
        source for source, source_route in actual_landing_routes.items()
        if source != satellite and satellite in source_route[1:-1]
    )
    return {
        "satellite_id": satellite,
        "actual_landing_route": route if valid_route else None,
        "next_hop_satellite_id": route[1] if valid_route else None,
        "landing_satellite_id": route[-1] if valid_route else None,
        "routed_via_by_satellites": routed_via_by,
        "route_child_count": len(routed_via_by),
        "is_terminal": valid_route and not routed_via_by,
    }


def group_interruptions(
    interruptions: list[dict[str, Any]],
    neighbors: Mapping[str, set[str]],
    preferred_satellites: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Only identical full boundaries merge; overlap/containment is not equality."""
    buckets: dict[tuple[datetime, datetime], set[str]] = {}
    for row in interruptions:
        start = parse_bdt(row["interruption_start_bdt"])
        end = parse_bdt(row["interruption_end_bdt"])
        if end <= start:
            raise ValueError("Interruption end must follow its start")
        buckets.setdefault((start, end), set()).add(row["satellite_id"])

    groups = []
    for (start, end), satellites in sorted(buckets.items()):
        remaining = set(satellites)
        order: list[str] = []
        seeds = [*(preferred_satellites or []), *sorted(satellites)]
        for seed in seeds:
            if seed not in remaining:
                continue
            remaining.remove(seed)
            pending = deque([seed])
            while pending:
                satellite = pending.popleft()
                order.append(satellite)
                adjacent = sorted(neighbors.get(satellite, set()) & remaining)
                remaining.difference_update(adjacent)
                pending.extend(adjacent)
        groups.append({
            "interruption_start_bdt": start.isoformat(sep=" ", timespec="milliseconds"),
            "interruption_end_bdt": end.isoformat(sep=" ", timespec="milliseconds"),
            "interruption_seconds": (end - start).total_seconds(),
            "satellites": sorted(satellites),
            "investigation_order": order,
        })
    return groups


def match_packetin_boundaries(
    events: list[dict[str, Any]],
    interruption_start: str,
    interruption_end: str,
) -> dict[str, Any]:
    matches: dict[str, Any] = {"tolerance_seconds": PACKETIN_TOLERANCE_SECONDS}
    for name, time, event_type in (
        ("down", interruption_start, "LINK_DOWN"),
        ("up", interruption_end, "LINK_UP"),
    ):
        boundary = parse_bdt(time)
        candidates = []
        for event in events:
            if event["event_type"] != event_type:
                continue
            delta = (parse_bdt(event["occurred_bdt"]) - boundary).total_seconds()
            if abs(delta) <= PACKETIN_TOLERANCE_SECONDS:
                candidates.append({
                    "packetin_id": event["packetin_id"],
                    "affected_link": event["affected_link"],
                    "occurred_bdt": event["occurred_bdt"],
                    "delta_seconds": delta,
                })
        matches[name] = candidates
    down_links = {event["affected_link"] for event in matches["down"]}
    up_links = {event["affected_link"] for event in matches["up"]}
    # Matching endpoints on different links is not a complete correspondence.
    matches["matched_links"] = sorted(down_links & up_links)
    matches["matched"] = bool(matches["matched_links"])
    return matches
