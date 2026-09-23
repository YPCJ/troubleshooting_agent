#!/usr/bin/env python3
"""Opt-in, additive enrichment of an existing SBC simulation database."""

import argparse
import sqlite3
from pathlib import Path

from generate_sbc_simulation_db import (
    enrich_observation_tables,
    replace_landing_updates_with_retries,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true",
        help="Add both observation tables in one transaction; default is read-only inspection.",
    )
    parser.add_argument(
        "--neutralize-topology-sources", action="store_true",
        help="With --apply, replace realtime change-source labels with a neutral acquisition source.",
    )
    parser.add_argument(
        "--add-uplink-retries", action="store_true",
        help="With --apply, migrate existing landing observations to 3-second retry attempts.",
    )
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    if args.apply and "V0.9-N" in database.name:
        parser.error("The V0.9-N backup must not be modified")
    mode = "rw" if args.apply else "ro"
    connection = sqlite3.connect(f"{database.as_uri()}?mode={mode}", uri=True)
    try:
        if args.apply:
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='landing_table_update_observation'"
                ).fetchone()
                if existing:
                    if not args.add_uplink_retries:
                        raise ValueError(
                            "Observation tables already exist; use --add-uplink-retries "
                            "for the retry migration"
                        )
                    replace_landing_updates_with_retries(connection)
                else:
                    enrich_observation_tables(connection)
                if args.neutralize_topology_sources:
                    connection.execute(
                        "UPDATE realtime_topology SET change_source=? WHERE change_source<>?",
                        ("星间拓扑状态采集", "星间拓扑状态采集"),
                    )
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity check failed")
        for table in ("ground_link_topology", "keepalive_landing_candidate",
                      "landing_table_update_observation", "onboard_routing_table_snapshot"):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if exists else None
            print(f"{table}: {count if exists else 'not present'}")
        print("Enrichment committed." if args.apply else "Read-only inspection; use --apply to enrich.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
