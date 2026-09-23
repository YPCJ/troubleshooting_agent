from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from backend.agents.sbc_network_troubleshooting.observation_rules import (
    PACKETIN_TOLERANCE_SECONDS,
    group_interruptions,
    match_packetin_boundaries,
    parse_bdt,
    terminal_node_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "sbc_simulation_20260808.db"
ToolHandler = Callable[[Mapping[str, Any]], dict[str, Any]]


def _database_path() -> Path:
    return Path(os.getenv("SBC_DATABASE_PATH", str(DEFAULT_DATABASE))).expanduser().resolve()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _database_path()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _rows(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (table_name,),
    ).fetchone() is not None


def _limit(arguments: Mapping[str, Any]) -> int:
    try:
        value = int(arguments.get("limit", 200))
    except (TypeError, ValueError):
        value = 200
    return max(1, min(value, 1000))


def _satellites(arguments: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    values.extend(arguments.get("affected_objects") or [])
    values.extend(
        [
            arguments.get("source_sat"),
            arguments.get("satellite_id"),
            arguments.get("sat_id"),
        ]
    )
    return list(
        dict.fromkeys(
            str(value).strip().upper()
            for value in values
            if value is not None and str(value).strip()
        )
    )


def _window(arguments: Mapping[str, Any]) -> tuple[str, str]:
    start = str(arguments.get("start_time") or "").strip()
    end = str(arguments.get("end_time") or "").strip()
    if not start or not end:
        raise ValueError("start_time and end_time are required")
    start_dt, end_dt = parse_bdt(start), parse_bdt(end)
    if end_dt <= start_dt:
        raise ValueError("end_time must follow start_time")
    return (
        start_dt.isoformat(sep=" ", timespec="milliseconds"),
        end_dt.isoformat(sep=" ", timespec="milliseconds"),
    )


def _in_filter(column: str, values: list[str]) -> tuple[str, list[str]]:
    if not values:
        return "", []
    return f" AND {column} IN ({','.join('?' for _ in values)})", values


def _observation_bdt(
    arguments: Mapping[str, Any], start: str, end: str,
) -> str:
    value = str(
        arguments.get("observation_bdt")
        or arguments.get("interruption_start_bdt")
        or start
    ).strip()
    observation = parse_bdt(value).isoformat(sep=" ", timespec="milliseconds")
    if not start <= observation < end:
        raise ValueError("observation_bdt must be inside the query window")
    return observation


def _actual_landing_routes(
    connection: sqlite3.Connection,
    observation: str,
) -> dict[str, Any]:
    snapshot = connection.execute(
        """SELECT MAX(queried_bdt) FROM onboard_routing_table_snapshot
           WHERE queried_bdt <= ?""",
        (observation,),
    ).fetchone()
    snapshot_bdt = snapshot[0] if snapshot else None
    if not snapshot_bdt:
        return {
            "status": "missing_data",
            "reason": "No onboard routing snapshot at or before observation_bdt",
        }
    snapshots = _rows(
        connection,
        """SELECT satellite_id, entries_json
           FROM onboard_routing_table_snapshot WHERE queried_bdt=?""",
        (snapshot_bdt,),
    )
    selected = _rows(
        connection,
        """SELECT c.source_satellite_id, c.landing_satellite_id,
                  c.candidate_id, c.priority, c.route_path_json
           FROM keepalive_landing_candidate AS c
           JOIN ground_link_topology AS g ON g.ground_link_id=c.ground_link_id
           WHERE c.is_selected=1
             AND c.valid_start_bdt <= ? AND c.valid_end_bdt > ?
             AND g.actual_start_bdt <= ? AND g.actual_end_bdt > ?
             AND g.feeder_realtime_status='正常'
             AND g.feeder_connectivity='连通'
           ORDER BY c.source_satellite_id""",
        (observation, observation, observation, observation),
    )
    prior_selected = _rows(
        connection,
        """SELECT c.source_satellite_id, c.landing_satellite_id,
                  c.candidate_id, c.priority, c.route_path_json,
                  c.valid_start_bdt, c.valid_end_bdt
           FROM keepalive_landing_candidate AS c
           WHERE c.is_selected=1 AND c.valid_start_bdt <= ?
           ORDER BY c.source_satellite_id, c.valid_end_bdt DESC,
                    c.valid_start_bdt DESC""",
        (observation,),
    )
    snapshot_entries = {
        row["satellite_id"]: json.loads(row["entries_json"]) for row in snapshots
    }
    missing_snapshots = sorted({
        row["source_satellite_id"] for row in selected
        if row["source_satellite_id"] not in snapshot_entries
    })
    if missing_snapshots:
        return {
            "status": "missing_data",
            "reason": "Incomplete onboard routing snapshots for active landing routes",
            "missing_satellites": missing_snapshots,
            "route_snapshot_bdt": snapshot_bdt,
        }
    routes: dict[str, list[str]] = {}
    selected_routes: dict[str, list[str]] = {}
    last_selected_routes: dict[str, list[str]] = {}
    selections: dict[str, dict[str, Any]] = {}
    for selection in selected:
        source = selection["source_satellite_id"]
        landing = selection["landing_satellite_id"]
        selections[source] = selection
        selected_routes[source] = json.loads(selection["route_path_json"])
        if source == landing:
            routes[source] = [source]
            continue
        entry = next((
            item for item in snapshot_entries[source]
            if item["destination_satellite_id"] == landing
        ), None)
        if entry and entry.get("reachable") and entry.get("path"):
            routes[source] = entry["path"]
    for selection in prior_selected:
        last_selected_routes.setdefault(
            selection["source_satellite_id"],
            json.loads(selection["route_path_json"]),
        )
    return {
        "status": "ok",
        "route_snapshot_bdt": snapshot_bdt,
        "sample_age_seconds": (
            parse_bdt(observation) - parse_bdt(snapshot_bdt)
        ).total_seconds(),
        "routes": routes,
        "selected_routes": selected_routes,
        "last_selected_routes": last_selected_routes,
        "selections": selections,
        "landing_satellites": {
            row["landing_satellite_id"] for row in selected
        },
        "snapshot_entries": snapshot_entries,
    }


def _realtime_neighbors(
    connection: sqlite3.Connection,
    satellite: str,
    observation: str,
) -> list[str]:
    rows = _rows(
        connection,
        """SELECT e.source_satellite_id, e.destination_satellite_id
           FROM topology_edge AS e
           JOIN realtime_topology AS t ON t.topology_id=e.topology_id
           WHERE e.topology_kind='实时' AND e.is_connected=1
             AND t.start_bdt <= ? AND t.end_bdt > ?
             AND (e.source_satellite_id=? OR e.destination_satellite_id=?)""",
        (observation, observation, satellite, satellite),
    )
    return sorted({
        row["destination_satellite_id"]
        if row["source_satellite_id"] == satellite
        else row["source_satellite_id"]
        for row in rows
        if row["source_satellite_id"] != row["destination_satellite_id"]
    })


def _interruption_event_id(group: Mapping[str, Any]) -> str:
    satellites = ",".join(sorted(str(item) for item in group.get("satellites", [])))
    identity = (
        f"{group.get('interruption_start_bdt', '')}|"
        f"{group.get('interruption_end_bdt', '')}|{satellites}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper()
    start = str(group.get("interruption_start_bdt", "")).replace("-", "").replace(":", "")
    compact_start = start.replace(" ", "T").replace(".", "")[:15]
    return f"INT-{compact_start}-{digest}"


def _classify_interruption_group(
    connection: sqlite3.Connection,
    group: Mapping[str, Any],
) -> dict[str, Any]:
    group_start = str(group["interruption_start_bdt"])
    group_end = str(group["interruption_end_bdt"])
    satellites = [str(item) for item in group.get("satellites", [])]
    if not _table_exists(connection, "ground_link_topology"):
        return {
            "event_id": _interruption_event_id(group),
            "interruption_start_bdt": group_start,
            "interruption_end_bdt": group_end,
            "duration_seconds": float(group.get("interruption_seconds") or 0),
            "satellites": satellites,
            "satellite_count": len(satellites),
            "pattern": "single_pass" if len(satellites) == 1 else "fixed_sat_batch",
            "landing_satellites": [],
            "investigation_order": list(group.get("investigation_order") or satellites),
        }
    if len(satellites) == 1:
        landing_rows = _rows(
            connection,
            """SELECT DISTINCT landing_satellite_id
               FROM ground_link_topology
               WHERE planned_start_bdt < ? AND planned_end_bdt > ?
               ORDER BY landing_satellite_id""",
            (group_end, group_start),
        )
        pattern = "single_sat_long" if len(landing_rows) > 1 else "single_pass"
    else:
        landing_rows = _rows(
            connection,
            """SELECT DISTINCT landing_satellite_id
               FROM ground_link_topology
               WHERE planned_start_bdt <= ? AND planned_end_bdt > ?
               ORDER BY landing_satellite_id""",
            (group_start, group_start),
        )
        pattern = "fixed_landing_sat" if len(landing_rows) == 1 else "fixed_sat_batch"
    landing_ids = [str(row["landing_satellite_id"]) for row in landing_rows]
    return {
        "event_id": _interruption_event_id(group),
        "interruption_start_bdt": group_start,
        "interruption_end_bdt": group_end,
        "duration_seconds": float(group.get("interruption_seconds") or 0),
        "satellites": satellites,
        "satellite_count": len(satellites),
        "pattern": pattern,
        "landing_satellites": landing_ids,
        "investigation_order": list(group.get("investigation_order") or satellites),
    }


def keep_alive_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    satellite_filter, satellite_parameters = _in_filter("satellite_id", satellites)
    with _connect() as connection:
        interruptions = _rows(
            connection,
            """
            SELECT satellite_id, interruption_start_bdt, interruption_end_bdt,
                   interruption_seconds
            FROM v_keepalive_interruptions
            WHERE interruption_start_bdt < ? AND interruption_end_bdt > ?
            ORDER BY interruption_start_bdt, satellite_id
            LIMIT ?
            """,
            (end, start, _limit(arguments) + 1),
        )
        records = _rows(
            connection,
            f"""
            SELECT keepalive_id, satellite_id, keepalive_start_bdt, keepalive_end_bdt
            FROM keepalive_statistics
            WHERE keepalive_start_bdt < ? AND keepalive_end_bdt > ?
            {satellite_filter}
            ORDER BY keepalive_start_bdt, satellite_id
            LIMIT ?
            """,
            (end, start, *satellite_parameters, _limit(arguments) + 1),
        )
        groups = group_interruptions(interruptions[:_limit(arguments)], {})
        candidate_events = [
            _classify_interruption_group(connection, group) for group in groups
        ]
        observation_value = str(arguments.get("observation_bdt") or "").strip()
        observation = (
            parse_bdt(observation_value).isoformat(sep=" ", timespec="milliseconds")
            if observation_value else None
        )
        candidates = [
            group for group in groups
            if observation
            and group["interruption_start_bdt"] <= observation
            < group["interruption_end_bdt"]
            and (
                not satellites
                or bool(set(group["satellites"]) & set(satellites))
            )
        ]
        primary = None
        pattern = "none"
        if len(candidates) == 1:
            primary = candidates[0]
        elif len(candidates) > 1:
            pattern = "multiple_sat_network"
        elif len(groups) == 1:
            primary = groups[0]
        elif groups:
            pattern = "multiple_sat_network"
        classification: dict[str, Any] = {"pattern": pattern}
        if primary:
            event = _classify_interruption_group(connection, primary)
            pattern = str(event["pattern"])
            classification = {
                "event_id": event["event_id"],
                "pattern": pattern,
                "interruption_start_bdt": event["interruption_start_bdt"],
                "interruption_end_bdt": event["interruption_end_bdt"],
                "satellites": event["satellites"],
                "landing_satellites": event["landing_satellites"],
            }
    truncated = len(interruptions) > _limit(arguments) or len(records) > _limit(arguments)
    interruptions = interruptions[:_limit(arguments)]
    affected = (
        classification.get("satellites")
        or sorted({row["satellite_id"] for row in interruptions})
    )
    return {
        "status": "ok",
        "anomaly": bool(affected),
        "affected_objects": affected,
        "pattern": classification["pattern"],
        "classification": classification,
        "data": records[:_limit(arguments)],
        "interruptions": interruptions,
        "interruption_groups": groups,
        "candidate_events": candidate_events,
        "truncated": truncated,
        "groups_complete": not truncated,
        "database": str(_database_path()),
    }


def connectionless_continuity_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    clause, values = _in_filter("satellite_id", _satellites(arguments))
    limit = _limit(arguments)
    with _connect() as connection:
        data = _rows(
            connection,
            f"""SELECT * FROM connectionless_continuity_statistics
                WHERE theoretical_start_bdt < ? AND theoretical_end_bdt > ? {clause}
                ORDER BY theoretical_start_bdt, satellite_id LIMIT ?""",
            (end, start, *values, limit + 1),
        )
        interruptions = _rows(
            connection,
            f"""SELECT * FROM v_keepalive_interruptions
                WHERE interruption_start_bdt < ? AND interruption_end_bdt > ? {clause}
                ORDER BY interruption_start_bdt, interruption_end_bdt, satellite_id LIMIT ?""",
            (end, start, *values, limit + 1),
        )
        groups = group_interruptions(interruptions[:limit], {})
        for group in groups:
            # Use planned neighbors at the event start so a failed link does not
            # erase the physical neighbor from the investigation priority.
            edges = _rows(
                connection,
                """SELECT e.source_satellite_id, e.destination_satellite_id
                   FROM topology_edge e JOIN planned_topology t ON t.topology_id=e.topology_id
                   WHERE e.topology_kind='规划' AND e.is_connected=1
                     AND t.start_bdt <= ? AND t.end_bdt > ?""",
                (group["interruption_start_bdt"], group["interruption_start_bdt"]),
            )
            neighbors: dict[str, set[str]] = {}
            for edge in edges:
                a, b = edge["source_satellite_id"], edge["destination_satellite_id"]
                neighbors.setdefault(a, set()).add(b)
                neighbors.setdefault(b, set()).add(a)
            members = [
                {"satellite_id": satellite, **group} for satellite in group["satellites"]
            ]
            group["investigation_order"] = group_interruptions(
                members, neighbors, _satellites(arguments)
            )[0]["investigation_order"]
    return {
        "status": "ok",
        "data": data[:limit],
        "interruption_groups": groups,
        "duration_basis": "full_stored_segment_not_clipped_to_query",
        "neighbor_basis": "planned_topology_at_interruption_start",
        "groups_complete": len(interruptions) <= limit,
        "truncated": len(data) > limit or len(interruptions) > limit,
    }


def topology_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    if tree_node == "E1" or arguments.get("check_terminal_node"):
        return _terminal_node_query(arguments, satellites, start, end)
    if tree_node in {"D4", "E2", "E6", "F1"}:
        return _topology_node_query(arguments, satellites, start, end, tree_node)
    with _connect() as connection:
        snapshots = _rows(
            connection,
            """
            SELECT topology_id, start_bdt, end_bdt, constellation, change_source
            FROM realtime_topology
            WHERE start_bdt < ? AND end_bdt > ?
            ORDER BY start_bdt
            LIMIT ?
            """,
            (end, start, _limit(arguments)),
        )
        edges: list[dict[str, Any]] = []
        if satellites:
            placeholders = ",".join("?" for _ in satellites)
            edges = _rows(
                connection,
                f"""
                SELECT e.topology_id, e.source_satellite_id, e.destination_satellite_id,
                       e.source_laser_id, e.destination_laser_id, e.is_connected
                FROM topology_edge AS e
                JOIN realtime_topology AS t ON t.topology_id=e.topology_id
                WHERE e.topology_kind='实时' AND t.start_bdt < ? AND t.end_bdt > ?
                  AND (e.source_satellite_id IN ({placeholders})
                       OR e.destination_satellite_id IN ({placeholders}))
                ORDER BY t.start_bdt, e.source_satellite_id, e.destination_satellite_id
                LIMIT ?
                """,
                (end, start, *satellites, *satellites, _limit(arguments)),
            )
    return {"status": "ok", "data": snapshots, "edges": edges}


def _topology_node_query(
    arguments: Mapping[str, Any],
    satellites: list[str],
    start: str,
    end: str,
    tree_node: str,
) -> dict[str, Any]:
    observation = _observation_bdt(arguments, start, end)
    if not satellites:
        raise ValueError(f"{tree_node} requires at least one affected satellite")
    with _connect() as connection:
        route_state = _actual_landing_routes(connection, observation)
        if route_state["status"] != "ok":
            return {**route_state, "data": []}
        routes: dict[str, list[str]] = route_state["routes"]
        if tree_node == "D4":
            selected_routes: dict[str, list[str]] = route_state["last_selected_routes"]
            route_sets = {
                satellite: set(selected_routes[satellite])
                for satellite in satellites if satellite in selected_routes
            }
            pending = set(route_sets)
            branches: list[list[str]] = []
            while pending:
                seed = min(pending)
                pending.remove(seed)
                branch = {seed}
                changed = True
                while changed:
                    changed = False
                    branch_nodes = set().union(*(route_sets[item] for item in branch))
                    attached = {
                        item for item in pending
                        if route_sets[item] & branch_nodes
                    }
                    if attached:
                        branch.update(attached)
                        pending.difference_update(attached)
                        changed = True
                branches.append(sorted(branch))
            missing = sorted(set(satellites) - set(route_sets))
            data = {
                "branches": sorted(branches),
                "branch_count": len(branches),
                "satellites_without_actual_landing_route": missing,
            }
            if missing:
                return {
                    "status": "missing_data", "data": [data],
                    "reason": "Affected satellites lack complete actual landing routes",
                    "route_snapshot_bdt": route_state["route_snapshot_bdt"],
                }
            return {
                "status": "ok", "data": [data],
                "outcome": "yes" if len(branches) > 1 else "no",
                "route_snapshot_bdt": route_state["route_snapshot_bdt"],
            }

        source = satellites[0]
        if tree_node == "E2":
            route = routes.get(source)
            return {
                "status": "ok",
                "data": [{"satellite_id": source, "actual_landing_route": route}],
                "outcome": "path_found" if route else "path_missing",
                "route_snapshot_bdt": route_state["route_snapshot_bdt"],
            }

        neighbors = _realtime_neighbors(connection, source, observation)
        landing_neighbors = [
            {
                "satellite_id": neighbor,
                "actual_landing_route": routes[neighbor],
            }
            for neighbor in neighbors if neighbor in routes
        ]
        data = {
            "satellite_id": source,
            "realtime_neighbors": neighbors,
            "neighbors_with_actual_landing_route": landing_neighbors,
        }
        if tree_node == "E6":
            return {
                "status": "ok", "data": [data],
                "outcome": "connected" if landing_neighbors else "not_connected",
                "route_snapshot_bdt": route_state["route_snapshot_bdt"],
            }
        packetin_exists = connection.execute(
            """SELECT 1 FROM packetin_message
               WHERE occurred_bdt >= ? AND occurred_bdt < ?
                 AND event_type IN ('LINK_DOWN', 'LINK_UP')
                 AND (affected_link LIKE ? OR reporting_satellite_id=?)
               LIMIT 1""",
            (start, end, f"%{source}%", source),
        ).fetchone()
    result = {
        "status": "ok", "data": [data],
        "route_snapshot_bdt": route_state["route_snapshot_bdt"],
    }
    if packetin_exists:
        result["decision_deferred_to"] = "packetin_query"
    else:
        result["outcome"] = "yes" if landing_neighbors else "no"
        result["decision_basis"] = "realtime_neighbors_and_actual_landing_routes"
    return result


def _terminal_node_query(
    arguments: Mapping[str, Any], satellites: list[str], start: str, end: str,
) -> dict[str, Any]:
    if len(satellites) != 1:
        raise ValueError("Terminal-node evaluation requires exactly one satellite")
    if not str(arguments.get("observation_bdt") or "").strip():
        raise ValueError("Terminal-node evaluation requires observation_bdt")
    observation = _observation_bdt(arguments, start, end)
    with _connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM satellite_basic_info WHERE satellite_id=?", (satellites[0],)
        ).fetchone()
        if not exists:
            return {"status": "missing_data", "data": [], "reason": "Unknown satellite"}
        route_state = _actual_landing_routes(connection, observation)
    if route_state["status"] != "ok":
        return {**route_state, "data": []}
    data = terminal_node_evidence(
        satellites[0],
        route_state["routes"],
        route_state["landing_satellites"],
    )
    return {
        "status": "ok", "observation_bdt": observation,
        "route_snapshot_bdt": route_state["route_snapshot_bdt"],
        "sample_age_seconds": route_state["sample_age_seconds"],
        "evaluated_actual_route_count": len(route_state["routes"]),
        "data": [data], "outcome": "yes" if data["is_terminal"] else "no",
    }


def packetin_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    links = str(arguments.get("affected_link") or "").strip()
    boundary_start = str(arguments.get("interruption_start_bdt") or "").strip()
    boundary_end = str(arguments.get("interruption_end_bdt") or "").strip()
    matching = bool(boundary_start or boundary_end) and tree_node not in {"F1", "F7"}
    if matching:
        if (
            not boundary_start
            or not boundary_end
            or not links and tree_node != "H17"
        ):
            raise ValueError(
                "Boundary matching requires interruption_start_bdt, "
                "interruption_end_bdt and affected_link"
            )
        if parse_bdt(boundary_end) <= parse_bdt(boundary_start):
            raise ValueError("Interruption end must follow its start")
        start = (parse_bdt(boundary_start) - timedelta(seconds=PACKETIN_TOLERANCE_SECONDS)).isoformat(sep=" ", timespec="milliseconds")
        end = (parse_bdt(boundary_end) + timedelta(seconds=PACKETIN_TOLERANCE_SECONDS)).isoformat(sep=" ", timespec="milliseconds")
    # Reporter is not necessarily an endpoint of the affected link.
    if matching and tree_node == "H17" and not links:
        clause, values = "", []
    elif not links and tree_node in {"F1", "F7"} and satellites:
        source = satellites[0]
        clause = " AND (affected_link LIKE ? OR reporting_satellite_id=?)"
        values = [f"%{source}%", source]
    else:
        clause, values = ("", []) if links else _in_filter("reporting_satellite_id", satellites)
    if links:
        clause += " AND affected_link=?"
        values.append(links)
    with _connect() as connection:
        data = _rows(
            connection,
            f"""
            SELECT * FROM packetin_message
            WHERE occurred_bdt {'<=' if matching else '<'} ? AND occurred_bdt >= ? {clause}
            ORDER BY occurred_bdt, message_sequence
            LIMIT ?
            """,
            (end, start, *values, _limit(arguments) + 1),
        )
    truncated = len(data) > _limit(arguments)
    result: dict[str, Any] = {"status": "ok", "data": data[:_limit(arguments)], "truncated": truncated}
    if not matching and tree_node in {"F1", "F7"}:
        link_events = [
            row for row in result["data"]
            if row["event_type"] in {"LINK_DOWN", "LINK_UP"}
        ]
        result["packetin_observed"] = bool(link_events)
        if not link_events:
            result["data"] = [{"packetin_observed": False}]
            result["decision_deferred_to"] = (
                "topology_query" if tree_node == "F1" else "laser_link_query"
            )
        elif tree_node == "F1":
            latest = link_events[-1]
            result["outcome"] = "yes" if latest["event_type"] == "LINK_UP" else "no"
            result["decision_basis"] = "packetin_latest_link_event"
        else:
            result["outcome"] = "normal"
            result["decision_basis"] = "packetin_presence"
    if matching:
        if truncated:
            result["matching_status"] = "incomplete"
        elif not data:
            result["data"] = [{"packetin_boundary_observed": False}]
            result["matching_status"] = "complete"
            result["outcome"] = "not_matched"
        else:
            result["boundary_match"] = match_packetin_boundaries(data, boundary_start, boundary_end)
            result["matching_status"] = "complete"
            result["outcome"] = "matched" if result["boundary_match"]["matched"] else "not_matched"
    return result


def landing_table_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    landing_satellite = str(arguments.get("landing_satellite_id") or "").strip().upper()
    satellites = (
        [landing_satellite]
        if landing_satellite
        else [] if tree_node in {"E3", "F5", "I3"}
        else _satellites(arguments)
    )
    station = str(arguments.get("target_station") or "").strip().upper()
    limit = _limit(arguments)
    with _connect() as connection:
        if tree_node in {"E3", "F5", "I3"} and not satellites:
            reference = str(
                arguments.get("interruption_start_bdt")
                or arguments.get("observation_bdt")
                or start
            )
            satellites = [
                row["landing_satellite_id"] for row in _rows(
                    connection,
                    """SELECT DISTINCT landing_satellite_id
                       FROM ground_link_topology
                       WHERE planned_start_bdt <= ? AND planned_end_bdt > ?
                       ORDER BY landing_satellite_id""",
                    (reference, reference),
                )
            ]
        clause, values = _in_filter("landing_satellite_id", satellites)
        if station:
            clause += " AND gateway_id=?"
            values.append(station)
        updates = _rows(
            connection,
            f"""
            SELECT update_id, MIN(observed_bdt) AS first_observed_bdt
            FROM landing_table_update_observation
            WHERE observed_bdt >= ? AND observed_bdt < ? {clause}
            GROUP BY update_id ORDER BY first_observed_bdt, update_id
            LIMIT ?
            """,
            (start, end, *values, limit + 1),
        )
        data: list[dict[str, Any]] = []
        summaries = []
        for update in updates[:limit]:
            records = _rows(
                connection,
                """SELECT * FROM landing_table_update_observation
                   WHERE update_id=? AND observed_bdt < ?
                   ORDER BY observed_bdt, observation_id""",
                (update["update_id"], end),
            )
            for record in records:
                record["candidate_ids"] = json.loads(record.pop("candidate_ids_json"))
            data.extend(records)
            uplink_records = [row for row in records if row["event_type"] == "uplink"]
            receipt_records = [
                row for row in records if row["event_type"] == "receipt_diffusion"
            ]
            summaries.append({
                "update_id": update["update_id"],
                "uplink_observed": bool(uplink_records),
                "uplink_attempt_count": len(uplink_records),
                "first_uplink_bdt": (
                    uplink_records[0]["observed_bdt"] if uplink_records else None
                ),
                "last_uplink_bdt": (
                    uplink_records[-1]["observed_bdt"] if uplink_records else None
                ),
                "receipt_diffusion_observed": bool(receipt_records),
                "receipt_bdt": (
                    receipt_records[0]["observed_bdt"] if receipt_records else None
                ),
                "receipt_attempt_no": (
                    receipt_records[0]["attempt_no"] if receipt_records else None
                ),
            })
    result = {
        "status": "ok", "data": data, "updates": summaries,
        "truncated": len(updates) > limit, "observation_cutoff_bdt": end,
        "absence_note": "No receipt observation is not proof of the failure cause.",
    }
    if tree_node == "E3":
        latest = summaries[-1] if summaries else {
            "uplink_observed": False,
            "receipt_diffusion_observed": False,
        }
        if not data:
            result["data"] = [{
                "uplink_observed": False,
                "receipt_diffusion_observed": False,
                "landing_satellite_ids": satellites,
            }]
        result["latest_update"] = latest
        result["outcome"] = (
            "responded" if latest["receipt_diffusion_observed"] else "not_responded"
        )
    elif tree_node == "I3":
        if not data:
            result["data"] = [{"direct_landing_receipt_observed": False}]
        result["outcome"] = "checked"
        result["missing_evidence"] = "邻居卫星扩散响应计数未获取"
    elif tree_node == "F5" and not data:
        result["data"] = [{"landing_update_observed": False}]
    return result


def feeder_link_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    satellites = [] if tree_node in {"E3", "F5"} else _satellites(arguments)
    clause, values = _in_filter("landing_satellite_id", satellites)
    target_station = str(arguments.get("target_station") or "").strip().upper()
    station_clause = " AND gateway_id=?" if target_station else ""
    station_values = [target_station] if target_station else []
    with _connect() as connection:
        data = _rows(
            connection,
            f"""
            SELECT * FROM ground_link_topology
            WHERE planned_start_bdt < ? AND planned_end_bdt > ?
            {clause}{station_clause}
            ORDER BY planned_start_bdt, landing_satellite_id
            LIMIT ?
            """,
            (end, start, *values, *station_values, _limit(arguments)),
        )
    result: dict[str, Any] = {"status": "ok", "data": data}
    if tree_node == "E3" and not data:
        result["data"] = [{"planned_feeder_observed": False}]
    if tree_node == "F5":
        interruption_start = str(arguments.get("interruption_start_bdt") or start)
        interruption_end = str(arguments.get("interruption_end_bdt") or end)
        checks = []
        for row in data:
            overlap_start = max(interruption_start, row["planned_start_bdt"])
            overlap_end = min(interruption_end, row["planned_end_bdt"])
            full_normal = (
                row["feeder_realtime_status"] == "正常"
                and row["feeder_connectivity"] == "连通"
                and row["actual_start_bdt"] <= overlap_start
                and row["actual_end_bdt"] >= overlap_end
            )
            checks.append({
                "ground_link_id": row["ground_link_id"],
                "tracking_arc_id": row["tracking_arc_id"],
                "overlap_start_bdt": overlap_start,
                "overlap_end_bdt": overlap_end,
                "full_overlap_normal": full_normal,
            })
        all_normal = bool(checks) and all(item["full_overlap_normal"] for item in checks)
        result["full_interruption_window_checks"] = checks
        result["outcome"] = "normal" if all_normal else "abnormal"
        if not data:
            result["data"] = [{
                "planned_feeder_observed": False,
                "interruption_start_bdt": interruption_start,
                "interruption_end_bdt": interruption_end,
            }]
    return result


def SBC_telemetry_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    if tree_node == "H2":
        return {
            "status": "ok",
            "data": [{
                "delayed_landing_table_receipt_telemetry_available": False,
            }],
            "outcome": "not_received",
            "missing_evidence": "无延时遥测，按“否”进入后续分支",
        }
    satellites = _satellites(arguments)
    router_clause, router_values = _in_filter("telemetry_source", satellites)
    laser_clause = ""
    laser_values: list[str] = []
    if satellites:
        laser_clause = (
            " AND ("
            + " OR ".join("laser_terminal_id LIKE ?" for _ in satellites)
            + ")"
        )
        laser_values = [f"{satellite}-L-%" for satellite in satellites]
    parameter = str(arguments.get("parameter_code") or arguments.get("parameter_name") or "").strip()
    parameter_clause = " AND (parameter_code=? OR parameter_name=?)" if parameter else ""
    parameter_values = [parameter, parameter] if parameter else []
    with _connect() as connection:
        router = _rows(
            connection,
            f"""
            SELECT 'router' AS telemetry_kind, * FROM router_telemetry
            WHERE reported_bdt >= ? AND reported_bdt < ? {router_clause}{parameter_clause}
            ORDER BY reported_bdt, telemetry_source
            LIMIT ?
            """,
            (start, end, *router_values, *parameter_values, _limit(arguments)),
        )
        laser = _rows(
            connection,
            f"""
            SELECT 'laser' AS telemetry_kind, * FROM laser_telemetry
            WHERE reported_bdt >= ? AND reported_bdt < ? {laser_clause}{parameter_clause}
            ORDER BY reported_bdt, telemetry_source
            LIMIT ?
            """,
            (start, end, *laser_values, *parameter_values, _limit(arguments)),
        )
    return {"status": "ok", "data": [*router, *laser]}


def route_table_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    clause, values = _in_filter("r.satellite_id", satellites)
    observation = str(arguments.get("observation_bdt") or "").strip()
    if observation:
        observation = parse_bdt(observation).isoformat(sep=" ", timespec="milliseconds")
        if not start <= observation < end:
            raise ValueError("observation_bdt must be inside the query window")
        time_clause = """r.queried_bdt = (
            SELECT MAX(s.queried_bdt) FROM onboard_routing_table_snapshot s
            WHERE s.satellite_id=r.satellite_id AND s.queried_bdt <= ?)"""
        time_values = (observation,)
    else:
        time_clause = "r.queried_bdt >= ? AND r.queried_bdt < ?"
        time_values = (start, end)
    destination = str(arguments.get("destination_satellite_id") or "").strip().upper()
    limit = _limit(arguments)
    with _connect() as connection:
        data = _rows(
            connection,
            f"""
            SELECT r.* FROM onboard_routing_table_snapshot AS r
            WHERE {time_clause} {clause}
            ORDER BY r.queried_bdt, r.satellite_id
            LIMIT ?
            """,
            (*time_values, *values, limit + 1),
        )
    for row in data[:limit]:
        entries = json.loads(row.pop("entries_json"))
        row["total_entry_count"] = len(entries)
        row["entries"] = [
            entry for entry in entries
            if not destination or entry["destination_satellite_id"] == destination
        ]
        if observation:
            row["sample_age_seconds"] = (
                parse_bdt(observation) - parse_bdt(row["queried_bdt"])
            ).total_seconds()
    result = {
        "status": "ok", "data": data[:limit], "truncated": len(data) > limit,
        "sampling_interval_seconds": 1800,
        "sampling_note": "Snapshot times are query times, not routing-change times. Never backdate later observations.",
    }
    if str(arguments.get("tree_node_id") or "") == "F8":
        normal = bool(result["data"]) and all(
            row["total_entry_count"] > 0
            and (
                not destination
                or bool(row["entries"])
                and all(entry.get("reachable") for entry in row["entries"])
            )
            for row in result["data"]
        )
        if not result["data"]:
            result["data"] = [{"routing_snapshot_observed": False}]
        result["outcome"] = "normal" if normal else "abnormal"
        result["decision_basis"] = "onboard_routing_table_snapshot_only"
    return result


def route_path_diagnosis(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    if not satellites:
        raise ValueError("Route-path diagnosis requires a source satellite")
    source = satellites[0]
    observation = _observation_bdt(arguments, start, end)
    with _connect() as connection:
        route_state = _actual_landing_routes(connection, observation)
        if route_state["status"] != "ok":
            return {**route_state, "data": []}
        routes: dict[str, list[str]] = route_state["last_selected_routes"]
        route_source = source
        route = routes.get(source)
        if not route:
            candidates = [
                (len(routes[neighbor]), neighbor, routes[neighbor])
                for neighbor in _realtime_neighbors(connection, source, observation)
                if neighbor in routes
            ]
            if candidates:
                _, route_source, route = min(candidates)
        if not route or len(route) < 2:
            return {
                "status": "missing_data",
                "data": [],
                "reason": "No actual landing route is available for hop-by-hop diagnosis",
                "satellite_id": source,
                "route_snapshot_bdt": route_state["route_snapshot_bdt"],
            }
        landing = route[-1]
        hop_checks = []
        for index, current in enumerate(route[:-1]):
            expected_next = route[index + 1]
            entries = route_state["snapshot_entries"].get(current)
            if entries is None:
                state = "missing_snapshot"
                entry = None
            elif not entries:
                state = "empty_route_table"
                entry = None
            else:
                entry = next((
                    item for item in entries
                    if item["destination_satellite_id"] == landing
                ), None)
                if entry is None:
                    state = "missing_destination_entry"
                elif not entry.get("reachable"):
                    state = "unreachable"
                elif entry.get("next_hop_satellite_id") != expected_next:
                    state = "next_hop_mismatch"
                else:
                    state = "normal"
            hop_checks.append({
                "satellite_id": current,
                "destination_landing_satellite_id": landing,
                "expected_next_hop_satellite_id": expected_next,
                "observed_entry": entry,
                "state": state,
            })
    abnormal = next(
        (item for item in hop_checks if item["state"] != "normal"),
        None,
    )
    return {
        "status": "ok",
        "data": hop_checks,
        "outcome": "checked",
        "requested_source_satellite_id": source,
        "diagnosed_route_source_satellite_id": route_source,
        "actual_landing_route": route,
        "route_snapshot_bdt": route_state["route_snapshot_bdt"],
        "sample_age_seconds": route_state["sample_age_seconds"],
        "first_abnormal_hop": abnormal,
    }


def laser_link_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    tree_node = str(arguments.get("tree_node_id") or "")
    if tree_node in {"F4", "F7", "I1"}:
        return _laser_asof_query(arguments, satellites, start, end, tree_node)
    filter_sql = ""
    values: list[Any] = []
    if satellites:
        placeholders = ",".join("?" for _ in satellites)
        filter_sql = (
            f" AND (satellite_a_id IN ({placeholders})"
            f" OR satellite_b_id IN ({placeholders}))"
        )
        values = [*satellites, *satellites]
    with _connect() as connection:
        data = _rows(
            connection,
            f"""
            SELECT * FROM laser_link_event
            WHERE changed_bdt >= ? AND changed_bdt < ? {filter_sql}
            ORDER BY changed_bdt, satellite_a_id, satellite_b_id
            LIMIT ?
            """,
            (start, end, *values, _limit(arguments)),
        )
    return {"status": "ok", "data": data}


def _laser_asof_query(
    arguments: Mapping[str, Any],
    satellites: list[str],
    start: str,
    end: str,
    tree_node: str,
) -> dict[str, Any]:
    if not satellites:
        raise ValueError(f"{tree_node} laser evaluation requires a source satellite")
    source = satellites[0]
    observation = _observation_bdt(arguments, start, end)
    destination = str(
        arguments.get("destination_satellite_id") or ""
    ).strip().upper()
    with _connect() as connection:
        if tree_node == "F7":
            packetin = _rows(
                connection,
                """SELECT packetin_id, event_type, affected_link, occurred_bdt
                   FROM packetin_message
                   WHERE occurred_bdt >= ? AND occurred_bdt < ?
                     AND event_type IN ('LINK_DOWN', 'LINK_UP')
                     AND (affected_link LIKE ? OR reporting_satellite_id=?)
                   ORDER BY occurred_bdt, message_sequence""",
                (start, end, f"%{source}%", source),
            )
            if packetin:
                return {
                    "status": "ok",
                    "data": [{
                        "packetin_observed": True,
                        "laser_check_skipped": True,
                    }],
                    "decision_deferred_to": "packetin_query",
                }
        peers = [destination] if destination else _realtime_neighbors(
            connection, source, observation
        )
        link_checks = []
        for peer in peers:
            events = _rows(
                connection,
                """SELECT * FROM laser_link_event
                   WHERE changed_bdt <= ?
                     AND ((satellite_a_id=? AND satellite_b_id=?)
                       OR (satellite_a_id=? AND satellite_b_id=?))
                   ORDER BY changed_bdt DESC, event_id DESC""",
                (observation, source, peer, peer, source),
            )
            latest_by_direction: dict[tuple[str, str], dict[str, Any]] = {}
            for event in events:
                latest_by_direction.setdefault(
                    (event["satellite_a_id"], event["satellite_b_id"]),
                    event,
                )
            terminal_ids = sorted({
                event["laser_a_id"] for event in latest_by_direction.values()
            })
            telemetry = []
            for terminal_id in terminal_ids:
                row = connection.execute(
                    """SELECT * FROM laser_telemetry
                       WHERE laser_terminal_id=? AND reported_bdt <= ?
                       ORDER BY reported_bdt DESC, telemetry_id DESC LIMIT 1""",
                    (terminal_id, observation),
                ).fetchone()
                if row:
                    telemetry.append(dict(row))
            both_directions_connected = (
                len(latest_by_direction) == 2
                and all(
                    event["link_status"] == "连通"
                    for event in latest_by_direction.values()
                )
            )
            both_ends_locked = (
                len(terminal_ids) == 2
                and len(telemetry) == 2
                and all(row["raw_value"] == "1" for row in telemetry)
            )
            link_checks.append({
                "source_satellite_id": source,
                "destination_satellite_id": peer,
                "latest_directional_events": list(latest_by_direction.values()),
                "latest_endpoint_telemetry": telemetry,
                "both_directions_connected": both_directions_connected,
                "both_ends_locked": both_ends_locked,
                "normal": both_directions_connected and both_ends_locked,
            })
    normal = bool(link_checks) and all(item["normal"] for item in link_checks)
    outcome = (
        ("locked" if normal else "unlocked")
        if tree_node == "I1"
        else ("normal" if normal else "abnormal")
    )
    return {
        "status": "ok",
        "data": link_checks or [{
            "source_satellite_id": source,
            "neighbor_link_observed": False,
        }],
        "observation_bdt": observation,
        "outcome": outcome,
        "decision_basis": "latest_link_event_and_both_endpoint_lock_telemetry",
    }


def packet_capture(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "missing_data",
        "data": [],
        "reason": "LAN/WAN分接口抓包数据本轮未模拟，普通packet_log不能替代",
    }


def alarm_event_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _window(arguments)
    satellites = _satellites(arguments)
    with _connect() as connection:
        network = _rows(
            connection,
            """
            SELECT 'network' AS alarm_kind, alarm_id, alarm_title AS title,
                   alarm_level, occurred_bdt, resolved_bdt,
                   network_element_name AS object_name, additional_info AS detail
            FROM network_alarm
            WHERE occurred_bdt < ? AND COALESCE(resolved_bdt, ?) > ?
            ORDER BY occurred_bdt
            LIMIT ?
            """,
            (end, end, start, _limit(arguments)),
        )
        satellite_filter, satellite_values = _in_filter("satellite_id", satellites)
        historical = _rows(
            connection,
            f"""
            SELECT 'satellite' AS alarm_kind, alarm_id, model_name AS title,
                   alarm_level, occurred_bdt, NULL AS resolved_bdt,
                   satellite_id AS object_name, alarm_message AS detail
            FROM satellite_historical_alarm
            WHERE occurred_bdt >= ? AND occurred_bdt < ? {satellite_filter}
            ORDER BY occurred_bdt
            LIMIT ?
            """,
            (start, end, *satellite_values, _limit(arguments)),
        )
        anomaly = _rows(
            connection,
            """
            SELECT 'measurement' AS alarm_kind, anomaly_id AS alarm_id,
                   '链路时延异常' AS title, '一般' AS alarm_level,
                   occurred_bdt, NULL AS resolved_bdt,
                   link_source || '->' || link_destination AS object_name,
                   CAST(link_delay_ms AS TEXT) || ' ms' AS detail
            FROM measurement_anomaly_alarm
            WHERE occurred_bdt >= ? AND occurred_bdt < ?
            ORDER BY occurred_bdt
            LIMIT ?
            """,
            (start, end, _limit(arguments)),
        )
    return {"status": "ok", "data": [*network, *historical, *anomaly]}


def build_sqlite_handlers() -> dict[str, ToolHandler]:
    handlers: dict[str, ToolHandler] = {
        "keep_alive_query": keep_alive_query,
        "connectionless_continuity_query": connectionless_continuity_query,
        "topology_query": topology_query,
        "packetin_query": packetin_query,
        "landing_table_query": landing_table_query,
        "feeder_link_query": feeder_link_query,
        "SBC_telemetry_query": SBC_telemetry_query,
        "route_table_query": route_table_query,
        "route_path_diagnosis": route_path_diagnosis,
        "laser_link_query": laser_link_query,
        "packet_capture": packet_capture,
        "alarm_event_query": alarm_event_query,
    }
    return {name: _safe_handler(handler) for name, handler in handlers.items()}


def _safe_handler(handler: ToolHandler) -> ToolHandler:
    def run(arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return handler(arguments)
        except (ValueError, sqlite3.Error, OSError) as exc:
            return {
                "status": "error",
                "error": str(exc),
                "data": [],
                "database": str(_database_path()),
            }

    return run
