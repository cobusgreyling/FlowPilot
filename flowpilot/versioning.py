"""Workflow versioning — track changes to workflows over time.

Stores versions in a SQLite database. Supports diff between versions,
rollback, and version history browsing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class WorkflowVersion:
    version: int
    workflow_id: str
    workflow_name: str
    data: dict
    created_at: str
    message: str

    @property
    def node_count(self) -> int:
        return len(self.data.get("nodes", []))

    def __str__(self) -> str:
        return f"v{self.version} ({self.created_at[:19]}) — {self.message} [{self.node_count} nodes]"


class WorkflowVersionStore:
    """Version control for workflow definitions."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(workflow_id, version)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_versions_workflow
                ON workflow_versions (workflow_id, version DESC)
            """)

    def save_version(self, workflow_id: str, workflow_name: str, data: dict, message: str = "") -> int:
        """Save a new version of a workflow. Returns version number."""
        current = self.get_latest_version(workflow_id)
        new_version = (current.version + 1) if current else 1

        # Skip if identical to current version
        if current and json.dumps(current.data, sort_keys=True) == json.dumps(data, sort_keys=True):
            return current.version

        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO workflow_versions
                   (workflow_id, workflow_name, version, data, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (workflow_id, workflow_name, new_version, json.dumps(data), message, now),
            )
        return new_version

    def get_version(self, workflow_id: str, version: int) -> WorkflowVersion | None:
        """Get a specific version."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """SELECT version, workflow_id, workflow_name, data, created_at, message
                   FROM workflow_versions WHERE workflow_id = ? AND version = ?""",
                (workflow_id, version),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def get_latest_version(self, workflow_id: str) -> WorkflowVersion | None:
        """Get the latest version of a workflow."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """SELECT version, workflow_id, workflow_name, data, created_at, message
                   FROM workflow_versions WHERE workflow_id = ?
                   ORDER BY version DESC LIMIT 1""",
                (workflow_id,),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def list_versions(self, workflow_id: str) -> list[WorkflowVersion]:
        """List all versions of a workflow."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """SELECT version, workflow_id, workflow_name, data, created_at, message
                   FROM workflow_versions WHERE workflow_id = ?
                   ORDER BY version DESC""",
                (workflow_id,),
            ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def diff(self, workflow_id: str, v1: int, v2: int) -> dict:
        """Compare two versions of a workflow."""
        ver1 = self.get_version(workflow_id, v1)
        ver2 = self.get_version(workflow_id, v2)
        if not ver1 or not ver2:
            return {"error": "Version not found"}

        nodes_v1 = {n["id"]: n for n in ver1.data.get("nodes", [])}
        nodes_v2 = {n["id"]: n for n in ver2.data.get("nodes", [])}

        added = [nid for nid in nodes_v2 if nid not in nodes_v1]
        removed = [nid for nid in nodes_v1 if nid not in nodes_v2]
        modified = []
        for nid in nodes_v1:
            if nid in nodes_v2 and nodes_v1[nid] != nodes_v2[nid]:
                modified.append({
                    "node_id": nid,
                    "before": nodes_v1[nid],
                    "after": nodes_v2[nid],
                })

        return {
            "v1": v1,
            "v2": v2,
            "nodes_added": added,
            "nodes_removed": removed,
            "nodes_modified": modified,
            "trigger_changed": ver1.data.get("trigger") != ver2.data.get("trigger"),
        }

    def rollback(self, workflow_id: str, to_version: int) -> WorkflowVersion | None:
        """Rollback to a previous version (creates a new version with old data)."""
        target = self.get_version(workflow_id, to_version)
        if not target:
            return None

        new_ver = self.save_version(
            workflow_id,
            target.workflow_name,
            target.data,
            message=f"Rollback to v{to_version}",
        )
        return self.get_version(workflow_id, new_ver)

    def _row_to_version(self, row: tuple) -> WorkflowVersion:
        return WorkflowVersion(
            version=row[0],
            workflow_id=row[1],
            workflow_name=row[2],
            data=json.loads(row[3]),
            created_at=row[4],
            message=row[5],
        )
