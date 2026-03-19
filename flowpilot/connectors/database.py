"""Database connector — SQLite and PostgreSQL read/write operations."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from flowpilot.connectors.base import BaseConnector


class DatabaseConnector(BaseConnector):
    """Database connector supporting SQLite and PostgreSQL."""

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url or os.environ.get("DATABASE_URL", "sqlite:///flowpilot_data.db")

    @property
    def name(self) -> str:
        return "database"

    def query(self, config: dict, context: dict) -> dict:
        """Execute a SELECT query and return results.

        Config:
            sql: SQL query string
            params: List of query parameters (optional)
            db_url: Override database URL (optional)
        """
        sql = config.get("sql", "")
        params = config.get("params", [])
        db_url = config.get("db_url") or self._db_url

        if not sql:
            return {"status": "error", "message": "No SQL query provided"}

        # Security check — only allow SELECT for query action
        if not sql.strip().upper().startswith("SELECT"):
            return {"status": "error", "message": "query() only allows SELECT statements. Use insert() or update() for writes."}

        return self._execute(db_url, sql, params, fetch=True)

    def insert(self, config: dict, context: dict) -> dict:
        """Execute an INSERT statement.

        Config:
            table: Table name
            data: Dict of column: value pairs
            db_url: Override database URL (optional)
        """
        table = config.get("table", "")
        data = config.get("data") or _extract_data(context)
        db_url = config.get("db_url") or self._db_url

        if not table or not data:
            return {"status": "error", "message": "Table name and data required"}

        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        return self._execute(db_url, sql, list(data.values()), fetch=False)

    def update(self, config: dict, context: dict) -> dict:
        """Execute an UPDATE statement.

        Config:
            table: Table name
            data: Dict of column: value pairs to update
            where: WHERE clause (e.g., "id = ?")
            where_params: Parameters for WHERE clause
            db_url: Override database URL (optional)
        """
        table = config.get("table", "")
        data = config.get("data", {})
        where = config.get("where", "")
        where_params = config.get("where_params", [])
        db_url = config.get("db_url") or self._db_url

        if not table or not data or not where:
            return {"status": "error", "message": "Table, data, and where clause required"}

        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = list(data.values()) + where_params

        return self._execute(db_url, sql, params, fetch=False)

    def _execute(self, db_url: str, sql: str, params: list, fetch: bool) -> dict:
        if db_url.startswith("sqlite"):
            return self._execute_sqlite(db_url, sql, params, fetch)
        elif db_url.startswith("postgresql"):
            return self._execute_postgres(db_url, sql, params, fetch)
        else:
            return {"status": "error", "message": f"Unsupported database: {db_url}"}

    def _execute_sqlite(self, db_url: str, sql: str, params: list, fetch: bool) -> dict:
        # Extract path from sqlite:///path
        db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
        if not db_path:
            db_path = "flowpilot_data.db"

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(sql, params)

                if fetch:
                    rows = cursor.fetchall()
                    data = [dict(row) for row in rows]
                    return {"status": "success", "data": data, "row_count": len(data)}
                else:
                    conn.commit()
                    return {"status": "success", "rows_affected": cursor.rowcount}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _execute_postgres(self, db_url: str, sql: str, params: list, fetch: bool) -> dict:
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            return {
                "status": "simulated",
                "message": "psycopg2 not installed. Install with: pip install psycopg2-binary",
            }

        try:
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(sql, params)

            if fetch:
                rows = cursor.fetchall()
                data = [dict(row) for row in rows]
                conn.close()
                return {"status": "success", "data": data, "row_count": len(data)}
            else:
                conn.commit()
                affected = cursor.rowcount
                conn.close()
                return {"status": "success", "rows_affected": affected}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def _extract_data(context: dict) -> dict:
    """Extract insertable data from context."""
    result = {}
    for key, val in context.items():
        if isinstance(val, dict):
            data = val.get("data")
            if isinstance(data, dict):
                result.update(data)
            elif val.get("text"):
                result[key] = val["text"]
        elif isinstance(val, (str, int, float)):
            result[key] = val
    return result
