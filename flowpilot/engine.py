"""Core workflow execution engine.

Executes workflow graphs with support for sequential and parallel
node execution, retry logic, error handling, and state management.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowNode:
    """A single step in a workflow graph."""
    id: str
    name: str
    connector: str
    action: str
    config: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    retry_count: int = 3
    retry_delay: float = 1.0
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at) * 1000)
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "connector": self.connector,
            "action": self.action,
            "config": self.config,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class WorkflowGraph:
    """A directed acyclic graph of workflow nodes."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    trigger: dict = field(default_factory=dict)

    def add_node(self, node: WorkflowNode) -> None:
        self.nodes.append(node)

    def get_node(self, node_id: str) -> WorkflowNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_ready_nodes(self) -> list[WorkflowNode]:
        """Return nodes whose dependencies are all satisfied."""
        ready = []
        for node in self.nodes:
            if node.status != NodeStatus.PENDING:
                continue
            deps_met = all(
                self.get_node(dep) and self.get_node(dep).status == NodeStatus.SUCCESS
                for dep in node.depends_on
            )
            if deps_met:
                ready.append(node)
        return ready

    def is_complete(self) -> bool:
        return all(
            n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED)
            for n in self.nodes
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowGraph:
        graph = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            trigger=data.get("trigger", {}),
        )
        for nd in data.get("nodes", []):
            graph.add_node(WorkflowNode(
                id=nd["id"],
                name=nd["name"],
                connector=nd["connector"],
                action=nd["action"],
                config=nd.get("config", {}),
                depends_on=nd.get("depends_on", []),
                retry_count=nd.get("retry_count", 3),
                retry_delay=nd.get("retry_delay", 1.0),
            ))
        return graph

    @classmethod
    def from_json(cls, json_str: str) -> WorkflowGraph:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: str) -> WorkflowGraph:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json())


class WorkflowEngine:
    """Async workflow execution engine with retry and parallel support."""

    def __init__(self):
        self._connectors: dict[str, Any] = {}

    def register_connector(self, name: str, connector: Any) -> None:
        self._connectors[name] = connector

    def execute(self, graph: WorkflowGraph, context: dict | None = None) -> dict:
        """Synchronous wrapper for workflow execution."""
        return asyncio.run(self.execute_async(graph, context or {}))

    async def execute_async(
        self, graph: WorkflowGraph, context: dict
    ) -> dict:
        """Execute a workflow graph asynchronously.

        Nodes with no unmet dependencies run in parallel.
        Failed nodes are retried up to their retry_count.
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        while not graph.is_complete():
            ready = graph.get_ready_nodes()
            if not ready:
                # Check for stuck nodes (dependencies that failed)
                for node in graph.nodes:
                    if node.status == NodeStatus.PENDING:
                        has_failed_dep = any(
                            self._node_failed(graph, dep)
                            for dep in node.depends_on
                        )
                        if has_failed_dep:
                            node.status = NodeStatus.SKIPPED
                            node.error = "Skipped due to failed dependency"
                continue

            tasks = [
                self._execute_node(node, graph, context)
                for node in ready
            ]
            await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start_time

        succeeded = sum(1 for n in graph.nodes if n.status == NodeStatus.SUCCESS)
        failed = sum(1 for n in graph.nodes if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in graph.nodes if n.status == NodeStatus.SKIPPED)

        return {
            "run_id": run_id,
            "workflow_id": graph.id,
            "status": "success" if failed == 0 else "partial_failure",
            "nodes_total": len(graph.nodes),
            "nodes_succeeded": succeeded,
            "nodes_failed": failed,
            "nodes_skipped": skipped,
            "duration_ms": int(elapsed * 1000),
            "results": {n.id: n.result for n in graph.nodes if n.result},
        }

    def _node_failed(self, graph: WorkflowGraph, node_id: str) -> bool:
        node = graph.get_node(node_id)
        return node is not None and node.status == NodeStatus.FAILED

    async def _execute_node(
        self, node: WorkflowNode, graph: WorkflowGraph, context: dict
    ) -> None:
        """Execute a single node with retry logic."""
        node.status = NodeStatus.RUNNING
        node.started_at = time.perf_counter()

        # Build input from dependency outputs
        node_input = dict(context)
        for dep_id in node.depends_on:
            dep = graph.get_node(dep_id)
            if dep and dep.result:
                node_input[dep_id] = dep.result

        for attempt in range(node.retry_count):
            try:
                connector = self._connectors.get(node.connector)
                if connector:
                    node.result = await self._run_connector(
                        connector, node.action, node.config, node_input
                    )
                else:
                    # Simulate execution for connectors not yet registered
                    node.result = {
                        "status": "simulated",
                        "connector": node.connector,
                        "action": node.action,
                        "message": f"Connector '{node.connector}' not registered — simulated success",
                    }

                node.status = NodeStatus.SUCCESS
                node.finished_at = time.perf_counter()
                return

            except Exception as e:
                if attempt < node.retry_count - 1:
                    await asyncio.sleep(node.retry_delay * (attempt + 1))
                else:
                    node.status = NodeStatus.FAILED
                    node.error = str(e)
                    node.finished_at = time.perf_counter()

    async def _run_connector(
        self, connector: Any, action: str, config: dict, context: dict
    ) -> Any:
        """Run a connector action, handling both sync and async."""
        method = getattr(connector, action, None)
        if not method:
            raise ValueError(f"Connector has no action '{action}'")

        if asyncio.iscoroutinefunction(method):
            return await method(config=config, context=context)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: method(config=config, context=context)
            )
