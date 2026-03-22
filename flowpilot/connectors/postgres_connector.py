"""PostgreSQL connector — query, insert, update, delete, and schema inspection."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from flowpilot.connectors.base import BaseConnector


class PostgresConnector(BaseConnector):
    """PostgreSQL integration via psycopg2.

    Supports raw SQL queries, insert/update/delete operations,
    and table listing. Falls back to simulated responses when
    credentials or the psycopg2 driver are unavailable.
    """

    def __init__(
        self,
        url: str | None = None,
        host: str | None = None,
        port: int | str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ):
        self._url = url or os.environ.get("POSTGRES_URL")
        self._host = host or os.environ.get("POSTGRES_HOST", "localhost")
        self._port = int(port or os.environ.get("POSTGRES_PORT", "5432"))
        self._user = user or os.environ.get("POSTGRES_USER")
        self._password = password or os.environ.get("POSTGRES_PASSWORD")
        self._database = database or os.environ.get("POSTGRES_DB")

    @property
    def name(self) -> str:
        return "postgres"

    @property
    def _has_credentials(self) -> bool:
        if self._url:
            return True
        return bool(self._host and self._user and self._database)

    def _get_connection(self) -> Any:
        """Create a psycopg2 connection."""
        import psycopg2

        if self._url:
            return psycopg2.connect(self._url)
        return psycopg2.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            dbname=self._database,
        )

    def validate_config(self, action: str, config: dict) -> list[str]:
        """Validate config for a specific action."""
        errors: list[str] = []
        if action == "query":
            if not config.get("sql"):
                errors.append("'sql' is required for query")
        elif action == "insert":
            if not config.get("table"):
                errors.append("'table' is required for insert")
            if not config.get("data"):
                errors.append("'data' (dict or list of dicts) is required for insert")
        elif action == "update":
            if not config.get("table"):
                errors.append("'table' is required for update")
            if not config.get("set"):
                errors.append("'set' (dict of column: value) is required for update")
            if not config.get("where"):
                errors.append("'where' (SQL condition string) is required for update")
        elif action == "delete":
            if not config.get("table"):
                errors.append("'table' is required for delete")
            if not config.get("where"):
                errors.append("'where' (SQL condition string) is required for delete")
        elif action == "list_tables":
            pass  # no required fields
        else:
            errors.append(f"Unknown action: {action}")
        return errors

    def query(self, config: dict, context: dict) -> dict:
        """Execute a read-only SQL query.

        Config:
            sql: SQL query string
            params: Query parameters (optional, list or tuple for %s placeholders)
            limit: Max rows to return (default 100)
        """
        sql = config.get("sql", "")
        params = config.get("params")
        limit = config.get("limit", 100)

        if not self._has_credentials:
            return {
                "status": "simulated",
                "sql": sql,
                "columns": ["id", "name", "email", "created_at"],
                "rows": [
                    [1, "Alice Johnson", "alice@example.com", "2026-01-15T10:00:00Z"],
                    [2, "Bob Smith", "bob@example.com", "2026-02-20T14:30:00Z"],
                    [3, "Carol White", "carol@example.com", "2026-03-10T09:15:00Z"],
                ],
                "row_count": 3,
                "message": "No PostgreSQL credentials configured — returning simulated query results",
            }

        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    columns = [desc[0] for desc in cur.description] if cur.description else []
                    rows = cur.fetchmany(limit)
                    row_count = cur.rowcount
                    # Convert rows to serializable lists
                    rows = [list(row) for row in rows]
                return {
                    "status": "success",
                    "columns": columns,
                    "rows": rows,
                    "row_count": row_count,
                }
            finally:
                conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def insert(self, config: dict, context: dict) -> dict:
        """Insert rows into a table.

        Config:
            table: Table name
            data: Dict (single row) or list of dicts (multiple rows)
                  Keys are column names, values are cell values.
        """
        table = config.get("table", "")
        data = config.get("data", {})

        # Normalise to list of dicts
        rows = data if isinstance(data, list) else [data]
        if not rows:
            return {"status": "error", "error": "No data provided"}

        columns = list(rows[0].keys())

        if not self._has_credentials:
            return {
                "status": "simulated",
                "table": table,
                "columns": columns,
                "rows_inserted": len(rows),
                "message": "No PostgreSQL credentials configured — insert simulated",
            }

        try:
            conn = self._get_connection()
            try:
                placeholders = ", ".join(["%s"] * len(columns))
                col_names = ", ".join(columns)
                sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

                with conn.cursor() as cur:
                    for row in rows:
                        values = [row.get(c) for c in columns]
                        cur.execute(sql, values)
                conn.commit()
                return {
                    "status": "success",
                    "table": table,
                    "rows_inserted": len(rows),
                }
            finally:
                conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def update(self, config: dict, context: dict) -> dict:
        """Update rows in a table.

        Config:
            table: Table name
            set: Dict of {column: new_value} to update
            where: SQL WHERE condition string (e.g. "id = 5")
            params: Parameters for the WHERE clause (optional)
        """
        table = config.get("table", "")
        set_data = config.get("set", {})
        where = config.get("where", "")
        params = config.get("params")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "table": table,
                "updated_columns": list(set_data.keys()),
                "where": where,
                "message": "No PostgreSQL credentials configured — update simulated",
            }

        try:
            conn = self._get_connection()
            try:
                set_clauses = ", ".join(f"{col} = %s" for col in set_data.keys())
                values = list(set_data.values())
                sql = f"UPDATE {table} SET {set_clauses} WHERE {where}"
                if params:
                    values.extend(params if isinstance(params, (list, tuple)) else [params])

                with conn.cursor() as cur:
                    cur.execute(sql, values)
                    rows_affected = cur.rowcount
                conn.commit()
                return {
                    "status": "success",
                    "table": table,
                    "rows_affected": rows_affected,
                }
            finally:
                conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def delete(self, config: dict, context: dict) -> dict:
        """Delete rows from a table.

        Config:
            table: Table name
            where: SQL WHERE condition string (e.g. "id = 5")
            params: Parameters for the WHERE clause (optional)
        """
        table = config.get("table", "")
        where = config.get("where", "")
        params = config.get("params")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "table": table,
                "where": where,
                "message": "No PostgreSQL credentials configured — delete simulated",
            }

        try:
            conn = self._get_connection()
            try:
                sql = f"DELETE FROM {table} WHERE {where}"
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows_affected = cur.rowcount
                conn.commit()
                return {
                    "status": "success",
                    "table": table,
                    "rows_deleted": rows_affected,
                }
            finally:
                conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def list_tables(self, config: dict, context: dict) -> dict:
        """List all tables in the database.

        Config:
            schema: Database schema to list (default "public")
        """
        schema = config.get("schema", "public")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "schema": schema,
                "tables": [
                    {"name": "users", "row_estimate": 15200},
                    {"name": "orders", "row_estimate": 84500},
                    {"name": "products", "row_estimate": 320},
                    {"name": "audit_log", "row_estimate": 1250000},
                ],
                "message": "No PostgreSQL credentials configured — returning simulated table list",
            }

        try:
            conn = self._get_connection()
            try:
                sql = """
                    SELECT c.relname AS table_name,
                           c.reltuples::bigint AS row_estimate
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relkind = 'r'
                    ORDER BY c.relname
                """
                with conn.cursor() as cur:
                    cur.execute(sql, (schema,))
                    tables = [
                        {"name": row[0], "row_estimate": row[1]}
                        for row in cur.fetchall()
                    ]
                return {"status": "success", "schema": schema, "tables": tables}
            finally:
                conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
