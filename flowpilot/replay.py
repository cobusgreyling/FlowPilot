"""Execution replay system for re-running failed workflows."""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .engine import WorkflowGraph, WorkflowEngine, NodeStatus


@dataclass
class ExecutionSnapshot:
    run_id: str
    workflow_id: str
    workflow_data: dict
    node_results: dict
    failed_node_id: Optional[str]
    status: str
    timestamp: str = ""
    duration_ms: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ReplayManager:
    """Save and replay workflow executions from point of failure."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_snapshots (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_data TEXT NOT NULL,
                    node_results TEXT NOT NULL,
                    failed_node_id TEXT,
                    status TEXT NOT NULL,
                    duration_ms REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workflow ON execution_snapshots(workflow_id)")
            conn.commit()

    def save_snapshot(self, workflow_graph: WorkflowGraph, result: dict) -> str:
        run_id = result.get("run_id", uuid.uuid4().hex[:12])
        failed_node = None
        for node in workflow_graph.nodes:
            if node.status == NodeStatus.FAILED:
                failed_node = node.id
                break

        node_results = {}
        for node in workflow_graph.nodes:
            node_results[node.id] = {
                "status": node.status.value if hasattr(node.status, 'value') else str(node.status),
                "result": result.get("results", {}).get(node.id),
                "error": node.error,
            }

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_snapshots (run_id, workflow_id, workflow_data, node_results, failed_node_id, status, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, workflow_graph.id, json.dumps(workflow_graph.to_dict()),
                 json.dumps(node_results), failed_node, result.get("status", "unknown"),
                 result.get("duration_ms", 0)),
            )
            conn.commit()
        return run_id

    def list_snapshots(self, workflow_id: Optional[str] = None, status_filter: Optional[str] = None) -> list[ExecutionSnapshot]:
        query = "SELECT run_id, workflow_id, workflow_data, node_results, failed_node_id, status, duration_ms, created_at FROM execution_snapshots WHERE 1=1"
        params = []
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        query += " ORDER BY created_at DESC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            return [
                ExecutionSnapshot(
                    run_id=r[0], workflow_id=r[1], workflow_data=json.loads(r[2]),
                    node_results=json.loads(r[3]), failed_node_id=r[4],
                    status=r[5], duration_ms=r[6], timestamp=r[7] or "",
                )
                for r in cursor.fetchall()
            ]

    def get_snapshot(self, run_id: str) -> Optional[ExecutionSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT run_id, workflow_id, workflow_data, node_results, failed_node_id, status, duration_ms, created_at FROM execution_snapshots WHERE run_id = ?",
                (run_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return ExecutionSnapshot(
                run_id=r[0], workflow_id=r[1], workflow_data=json.loads(r[2]),
                node_results=json.loads(r[3]), failed_node_id=r[4],
                status=r[5], duration_ms=r[6], timestamp=r[7] or "",
            )

    def replay_from_failure(self, run_id: str, engine: WorkflowEngine) -> dict:
        snapshot = self.get_snapshot(run_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {run_id}")
        if not snapshot.failed_node_id:
            raise ValueError(f"No failed node in snapshot {run_id}")

        graph = WorkflowGraph.from_dict(snapshot.workflow_data)

        # Restore successful nodes and reset failed/pending
        for node in graph.nodes:
            prev = snapshot.node_results.get(node.id, {})
            prev_status = prev.get("status", "pending")
            if prev_status == "success":
                node.status = NodeStatus.SUCCESS
                node.result = prev.get("result")
            else:
                node.status = NodeStatus.PENDING
                node.result = None
                node.error = None

        result = engine.execute(graph)
        self.save_snapshot(graph, result)
        return result

    def replay_single_node(self, run_id: str, node_id: str, engine: WorkflowEngine) -> dict:
        snapshot = self.get_snapshot(run_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {run_id}")

        graph = WorkflowGraph.from_dict(snapshot.workflow_data)

        # Mark all nodes as success except the target
        for node in graph.nodes:
            if node.id == node_id:
                node.status = NodeStatus.PENDING
                node.result = None
                node.error = None
            else:
                prev = snapshot.node_results.get(node.id, {})
                node.status = NodeStatus.SUCCESS
                node.result = prev.get("result")

        result = engine.execute(graph)
        return result

    def delete_snapshot(self, run_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM execution_snapshots WHERE run_id = ?", (run_id,))
            conn.commit()

    def cleanup(self, days_old: int = 30):
        cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM execution_snapshots WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount
