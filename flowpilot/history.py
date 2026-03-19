"""Execution history — SQLite-backed audit log of workflow runs.

Records every workflow execution with timestamps, status, node results,
and errors for debugging and observability.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RunRecord:
    """A single workflow execution record."""
    run_id: str
    workflow_id: str
    workflow_name: str
    status: str
    nodes_total: int
    nodes_succeeded: int
    nodes_failed: int
    nodes_skipped: int
    duration_ms: int
    started_at: str
    details: dict

    def __str__(self) -> str:
        return (
            f"[{self.started_at}] {self.workflow_name} "
            f"({self.status}) {self.duration_ms}ms "
            f"— {self.nodes_succeeded}/{self.nodes_total} succeeded"
        )


class ExecutionHistory:
    """SQLite-backed execution history and audit log."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    nodes_total INTEGER NOT NULL,
                    nodes_succeeded INTEGER NOT NULL,
                    nodes_failed INTEGER NOT NULL,
                    nodes_skipped INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    details TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_workflow
                ON runs (workflow_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_started
                ON runs (started_at DESC)
            """)

    def record(self, workflow_id: str, workflow_name: str, result: dict) -> str:
        """Record a workflow execution result."""
        run_id = result.get("run_id", str(uuid.uuid4())[:8])
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO runs
                   (run_id, workflow_id, workflow_name, status,
                    nodes_total, nodes_succeeded, nodes_failed, nodes_skipped,
                    duration_ms, started_at, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    workflow_id,
                    workflow_name,
                    result.get("status", "unknown"),
                    result.get("nodes_total", 0),
                    result.get("nodes_succeeded", 0),
                    result.get("nodes_failed", 0),
                    result.get("nodes_skipped", 0),
                    result.get("duration_ms", 0),
                    now,
                    json.dumps(result),
                ),
            )
        return run_id

    def list_runs(
        self,
        workflow_id: str | None = None,
        limit: int = 20,
    ) -> list[RunRecord]:
        """List execution history, most recent first."""
        with sqlite3.connect(self._db_path) as conn:
            if workflow_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?",
                    (workflow_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [self._row_to_record(r) for r in rows]

    def get_run(self, run_id: str) -> RunRecord | None:
        """Get a specific run by ID."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_stats(self, workflow_id: str | None = None) -> dict:
        """Get aggregate statistics for workflow runs."""
        with sqlite3.connect(self._db_path) as conn:
            where = "WHERE workflow_id = ?" if workflow_id else ""
            params = (workflow_id,) if workflow_id else ()

            row = conn.execute(
                f"""SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failures,
                    AVG(duration_ms) as avg_duration,
                    MIN(duration_ms) as min_duration,
                    MAX(duration_ms) as max_duration
                FROM runs {where}""",
                params,
            ).fetchone()

        return {
            "total_runs": row[0],
            "successes": row[1] or 0,
            "failures": row[2] or 0,
            "success_rate": round((row[1] or 0) / row[0] * 100, 1) if row[0] > 0 else 0,
            "avg_duration_ms": int(row[3] or 0),
            "min_duration_ms": row[4] or 0,
            "max_duration_ms": row[5] or 0,
        }

    def clear(self, workflow_id: str | None = None) -> int:
        """Clear execution history. Returns number of records deleted."""
        with sqlite3.connect(self._db_path) as conn:
            if workflow_id:
                cursor = conn.execute(
                    "DELETE FROM runs WHERE workflow_id = ?", (workflow_id,)
                )
            else:
                cursor = conn.execute("DELETE FROM runs")
            return cursor.rowcount

    def _row_to_record(self, row: tuple) -> RunRecord:
        return RunRecord(
            run_id=row[0],
            workflow_id=row[1],
            workflow_name=row[2],
            status=row[3],
            nodes_total=row[4],
            nodes_succeeded=row[5],
            nodes_failed=row[6],
            nodes_skipped=row[7],
            duration_ms=row[8],
            started_at=row[9],
            details=json.loads(row[10]),
        )
