"""Error budget and SLA tracking for workflows.

Monitors success rates per workflow over time. Alerts when a workflow
drops below its SLA threshold. Tracks error budget consumption.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class SLAStatus:
    workflow_id: str
    workflow_name: str
    sla_target: float
    current_rate: float
    total_runs: int
    successes: int
    failures: int
    error_budget_total: float
    error_budget_remaining: float
    error_budget_pct: float
    status: str  # healthy, warning, breached
    window_hours: int

    def __str__(self) -> str:
        return (
            f"{self.workflow_name}: {self.current_rate:.1f}% "
            f"(target {self.sla_target:.1f}%) — {self.status.upper()} "
            f"— budget {self.error_budget_pct:.0f}% remaining"
        )


class SLATracker:
    """Track SLA compliance and error budgets per workflow."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self._db_path = db_path
        self._sla_targets: dict[str, float] = {}
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sla_targets (
                    workflow_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    target_pct REAL NOT NULL DEFAULT 99.0,
                    window_hours INTEGER NOT NULL DEFAULT 168
                )
            """)

    def set_target(self, workflow_id: str, workflow_name: str, target_pct: float = 99.0, window_hours: int = 168) -> None:
        """Set SLA target for a workflow.

        Args:
            workflow_id: Workflow identifier
            workflow_name: Human-readable name
            target_pct: Target success rate (0-100, default 99%)
            window_hours: Rolling window in hours (default 168 = 7 days)
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO sla_targets (workflow_id, workflow_name, target_pct, window_hours)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(workflow_id) DO UPDATE SET
                   workflow_name=?, target_pct=?, window_hours=?""",
                (workflow_id, workflow_name, target_pct, window_hours,
                 workflow_name, target_pct, window_hours),
            )

    def get_status(self, workflow_id: str) -> SLAStatus | None:
        """Get current SLA status for a workflow."""
        with sqlite3.connect(self._db_path) as conn:
            target_row = conn.execute(
                "SELECT workflow_name, target_pct, window_hours FROM sla_targets WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()

        if not target_row:
            return None

        name, target_pct, window_hours = target_row
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes
                FROM runs
                WHERE workflow_id = ? AND started_at >= ?""",
                (workflow_id, cutoff),
            ).fetchone()

        total = row[0] or 0
        successes = row[1] or 0
        failures = total - successes

        current_rate = (successes / total * 100) if total > 0 else 100.0
        error_budget_total = (100 - target_pct) / 100 * total if total > 0 else 0
        error_budget_used = failures
        error_budget_remaining = max(0, error_budget_total - error_budget_used)
        error_budget_pct = (error_budget_remaining / error_budget_total * 100) if error_budget_total > 0 else 100.0

        if current_rate >= target_pct:
            status = "healthy"
        elif error_budget_remaining > 0:
            status = "warning"
        else:
            status = "breached"

        return SLAStatus(
            workflow_id=workflow_id,
            workflow_name=name,
            sla_target=target_pct,
            current_rate=round(current_rate, 2),
            total_runs=total,
            successes=successes,
            failures=failures,
            error_budget_total=round(error_budget_total, 2),
            error_budget_remaining=round(error_budget_remaining, 2),
            error_budget_pct=round(error_budget_pct, 1),
            status=status,
            window_hours=window_hours,
        )

    def get_all_statuses(self) -> list[SLAStatus]:
        """Get SLA status for all tracked workflows."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT workflow_id FROM sla_targets").fetchall()
        statuses = []
        for row in rows:
            status = self.get_status(row[0])
            if status:
                statuses.append(status)
        return statuses

    def check_alerts(self) -> list[str]:
        """Check for SLA breaches and warnings."""
        alerts = []
        for status in self.get_all_statuses():
            if status.status == "breached":
                alerts.append(
                    f"BREACH: {status.workflow_name} at {status.current_rate:.1f}% "
                    f"(target {status.sla_target:.1f}%) — error budget exhausted"
                )
            elif status.status == "warning":
                alerts.append(
                    f"WARNING: {status.workflow_name} — error budget at {status.error_budget_pct:.0f}%"
                )
        return alerts
