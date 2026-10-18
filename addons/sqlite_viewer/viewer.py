#!/usr/bin/env python3
"""Local, read-only SQLite browser for the offline SBC package."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = APP_ROOT / "data" / "sbc_simulation_20260808.db"
MAX_PAGE_SIZE = 200


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def preview(value: object) -> object:
    if isinstance(value, bytes):
        return f"BLOB ({len(value)} bytes): {value[:32].hex()}"
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + f"… [截断，原长 {len(value)} 字符]"
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


class SQLiteBrowser:
    def __init__(self, database: Path):
        self.database = database.resolve()
        if not self.database.is_file():
            raise FileNotFoundError(f"数据库不存在：{self.database}")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def objects(self) -> list[dict[str, str]]:
        with closing(self.connect()) as connection:
            return [
                {"name": row["name"], "type": row["type"]}
                for row in connection.execute(
                    "SELECT name, type FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY type, name"
                )
            ]

    def schema(self, name: str) -> dict[str, object]:
        objects = {item["name"]: item["type"] for item in self.objects()}
        if name not in objects:
            raise KeyError("表或视图不存在")
        with closing(self.connect()) as connection:
            columns = [
                {
                    "name": row["name"],
                    "type": row["type"] or "",
                    "not_null": bool(row["notnull"]),
                    "primary_key": bool(row["pk"]),
                }
                for row in connection.execute(f"PRAGMA table_xinfo({quote_identifier(name)})")
                if row["hidden"] == 0
            ]
        return {"name": name, "type": objects[name], "columns": columns}

    @staticmethod
    def where_clause(
        columns: list[dict[str, object]], filter_column: str, filter_text: str
    ) -> tuple[str, list[str]]:
        if not filter_text:
            return "", []
        if filter_column not in {str(column["name"]) for column in columns}:
            raise ValueError("请选择有效的筛选字段")
        literal = (
            filter_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return f" WHERE CAST({quote_identifier(filter_column)} AS TEXT) LIKE ? ESCAPE '\\'", [
            f"%{literal}%"
        ]

    def rows(
        self,
        name: str,
        page: int = 1,
        page_size: int = 50,
        filter_column: str = "",
        filter_text: str = "",
    ) -> dict[str, object]:
        if page < 1 or page > 100000 or page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ValueError("页码或每页条数超出范围")
        schema = self.schema(name)
        columns = schema["columns"]
        if not columns:
            return {"schema": schema, "page": page, "page_size": page_size, "total": 0, "rows": []}
        where, params = self.where_clause(columns, filter_column, filter_text)
        quoted = quote_identifier(name)
        order_columns = [column["name"] for column in columns if column["primary_key"]]
        if not order_columns:
            order_columns = [columns[0]["name"]]
        order = ", ".join(quote_identifier(str(column)) for column in order_columns)
        with closing(self.connect()) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM {quoted}{where}", params
            ).fetchone()[0]
            found = connection.execute(
                f"SELECT * FROM {quoted}{where} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "schema": schema,
            "page": page,
            "page_size": page_size,
            "total": total,
            "rows": [
                [preview(row[str(column["name"])]) for column in columns] for row in found
            ],
        }

    def chart(
        self,
        name: str,
        category: str,
        aggregate: str = "count",
        value_column: str = "",
        filter_column: str = "",
        filter_text: str = "",
    ) -> dict[str, object]:
        schema = self.schema(name)
        columns = schema["columns"]
        names = {str(column["name"]) for column in columns}
        if category not in names:
            raise ValueError("请选择有效的分组字段")
        if aggregate not in {"count", "sum", "avg"}:
            raise ValueError("不支持的统计方式")
        if aggregate != "count" and value_column not in names:
            raise ValueError("请选择有效的数值字段")
        where, params = self.where_clause(columns, filter_column, filter_text)
        category_sql = f"COALESCE(CAST({quote_identifier(category)} AS TEXT), '(空值)')"
        if aggregate == "count":
            metric_sql = "COUNT(*)"
        else:
            metric_sql = f"{aggregate.upper()}(CAST({quote_identifier(value_column)} AS REAL))"
        sql = (
            f"SELECT {category_sql} AS label, {metric_sql} AS metric "
            f"FROM {quote_identifier(name)}{where} GROUP BY {category_sql} "
            "ORDER BY metric DESC LIMIT 20"
        )
        with closing(self.connect()) as connection:
            found = connection.execute(sql, params).fetchall()
        return {
            "name": name,
            "category": category,
            "aggregate": aggregate,
            "items": [
                {"label": str(row["label"])[:160], "value": preview(row["metric"])}
                for row in found
            ],
        }


def make_handler(browser: SQLiteBrowser, port: int):
    html = Path(__file__).with_name("index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, message: str, *args: object) -> None:
            print(f"{self.client_address[0]} - {message % args}", flush=True)

        def send_body(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, value: object, status: int = 200) -> None:
            self.send_body(
                json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                "application/json; charset=utf-8",
                status,
            )

        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Host") not in {
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            }:
                self.send_json({"message": "仅允许本机访问"}, 403)
                return
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query, keep_blank_values=True)
            one = lambda key, default="": params.get(key, [default])[0]
            try:
                if parsed.path == "/":
                    self.send_body(html, "text/html; charset=utf-8")
                elif parsed.path == "/api/objects":
                    self.send_json({"database": browser.database.name, "items": browser.objects()})
                elif parsed.path == "/api/schema":
                    self.send_json(browser.schema(one("name")))
                elif parsed.path == "/api/rows":
                    self.send_json(
                        browser.rows(
                            one("name"),
                            int(one("page", "1")),
                            int(one("page_size", "50")),
                            one("filter_column"),
                            one("filter_text"),
                        )
                    )
                elif parsed.path == "/api/chart":
                    self.send_json(
                        browser.chart(
                            one("name"),
                            one("category"),
                            one("aggregate", "count"),
                            one("value_column"),
                            one("filter_column"),
                            one("filter_text"),
                        )
                    )
                else:
                    self.send_json({"message": "未找到页面"}, 404)
            except KeyError as exc:
                self.send_json({"message": str(exc)}, 404)
            except (ValueError, sqlite3.Error) as exc:
                self.send_json({"message": str(exc)}, 400)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="本机只读 SQLite 可视化查看器")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间")
    browser = SQLiteBrowser(args.database)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(browser, args.port))
    print(f"只读数据库：{browser.database}", flush=True)
    print(f"浏览器打开：http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
