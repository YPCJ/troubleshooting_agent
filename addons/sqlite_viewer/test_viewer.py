from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from addons.sqlite_viewer.viewer import SQLiteBrowser


class SQLiteBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "sample.db"
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, satellite TEXT, level INTEGER)")
                connection.executemany(
                    "INSERT INTO events (satellite, level) VALUES (?, ?)",
                    [("星01", 2), ("星01", 4), ("星02", 5)],
                )
                connection.execute("CREATE VIEW event_view AS SELECT satellite, level FROM events")
        self.browser = SQLiteBrowser(self.database)

    def test_rows_filter_and_chart(self) -> None:
        self.assertEqual(len(self.browser.objects()), 2)
        result = self.browser.rows("events", page=1, page_size=1)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["rows"][0], [1, "星01", 2])
        filtered = self.browser.rows("events", filter_column="satellite", filter_text="星01")
        self.assertEqual(filtered["total"], 2)
        chart = self.browser.chart("events", "satellite", "sum", "level")
        self.assertEqual(chart["items"][0], {"label": "星01", "value": 6.0})

    def test_identifiers_are_validated_and_database_is_read_only(self) -> None:
        with self.assertRaises(KeyError):
            self.browser.rows('events"; DROP TABLE events; --')
        with self.assertRaises(ValueError):
            self.browser.rows("events", filter_column="missing", filter_text="x")
        with closing(self.browser.connect()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM events")
        self.assertEqual(self.browser.rows("events")["total"], 3)


if __name__ == "__main__":
    unittest.main()
