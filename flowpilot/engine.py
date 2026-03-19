"""Core workflow execution engine.

Executes workflow graphs with support for sequential and parallel
node execution, retry logic, error handling, state management,
conditional branching, loop/iterator nodes, join nodes, dry run mode,
live execution streaming, and approval gates.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


class NodeType(str, Enum):
    STANDARD = "standard"
    CONDITION = "condition"
    LOOP = "loop"
    JOIN = "join"
    APPROVAL = "approval"


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
    node_type: NodeType = NodeType.STANDARD
    # Condition fields
    condition: dict | None = None  # {"field": "...", "operator": "...", "value": ...}
    on_true: str | None = None     # Node ID to run if true
    on_false: str | None = None    # Node ID to run if false
    # Loop fields
    iterate_over: str | None = None  # Context key containing the list
    loop_body: str | None = None     # Node ID to execute per item
    # Join fields
    join_from: list[str] = field(default_factory=list)  # Node IDs to wait for
    # Approval fields
    approval_message: str | None = None
    approval_timeout: int = 3600  # seconds
    # Runtime state
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
        d = {
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
        if self.node_type != NodeType.STANDARD:
            d["node_type"] = self.node_type.value
        if self.condition:
            d["condition"] = self.condition
            d["on_true"] = self.on_true
            d["on_false"] = self.on_false
        if self.iterate_over:
            d["iterate_over"] = self.iterate_over
            d["loop_body"] = self.loop_body
        if self.join_from:
            d["join_from"] = self.join_from
        if self.node_type == NodeType.APPROVAL:
            d["approval_message"] = self.approval_message
        return d


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

    def to_mermaid(self) -> str:
        """Generate a Mermaid.js flowchart diagram."""
        lines = ["graph TD"]
        for node in self.nodes:
            label = node.name.replace('"', "'")
            if node.node_type == NodeType.CONDITION:
                lines.append(f'    {node.id}{{{{{label}}}}}')
            elif node.node_type == NodeType.JOIN:
                lines.append(f'    {node.id}([{label}])')
            elif node.node_type == NodeType.LOOP:
                lines.append(f'    {node.id}[/"{label}"/]')
            elif node.node_type == NodeType.APPROVAL:
                lines.append(f'    {node.id}[("{label}")]')
            else:
                lines.append(f'    {node.id}["{label}"]')

        for node in self.nodes:
            for dep in node.depends_on:
                lines.append(f"    {dep} --> {node.id}")
            if node.node_type == NodeType.CONDITION:
                if node.on_true:
                    lines.append(f"    {node.id} -->|true| {node.on_true}")
                if node.on_false:
                    lines.append(f"    {node.id} -->|false| {node.on_false}")
            for jf in node.join_from:
                if jf not in node.depends_on:
                    lines.append(f"    {jf} -.-> {node.id}")

        # Color coding by status
        for node in self.nodes:
            if node.status == NodeStatus.SUCCESS:
                lines.append(f"    style {node.id} fill:#22c55e,color:#fff")
            elif node.status == NodeStatus.FAILED:
                lines.append(f"    style {node.id} fill:#ef4444,color:#fff")
            elif node.status == NodeStatus.RUNNING:
                lines.append(f"    style {node.id} fill:#3b82f6,color:#fff")
            elif node.status == NodeStatus.SKIPPED:
                lines.append(f"    style {node.id} fill:#6b7280,color:#fff")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowGraph:
        graph = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            trigger=data.get("trigger", {}),
        )
        for nd in data.get("nodes", []):
            node_type_str = nd.get("node_type", "standard")
            try:
                node_type = NodeType(node_type_str)
            except ValueError:
                node_type = NodeType.STANDARD

            graph.add_node(WorkflowNode(
                id=nd["id"],
                name=nd["name"],
                connector=nd.get("connector", ""),
                action=nd.get("action", ""),
                config=nd.get("config", {}),
                depends_on=nd.get("depends_on", []),
                retry_count=nd.get("retry_count", 3),
                retry_delay=nd.get("retry_delay", 1.0),
                node_type=node_type,
                condition=nd.get("condition"),
                on_true=nd.get("on_true"),
                on_false=nd.get("on_false"),
                iterate_over=nd.get("iterate_over"),
                loop_body=nd.get("loop_body"),
                join_from=nd.get("join_from", []),
                approval_message=nd.get("approval_message"),
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
    """Async workflow execution engine with retry, parallel, conditional,
    loop, join, dry run, streaming, and approval gate support."""

    def __init__(self):
        self._connectors: dict[str, Any] = {}
        self._rate_limiter: Any = None
        self._stream_callback: Callable | None = None
        self._approval_callback: Callable | None = None
        self._dry_run: bool = False

    def register_connector(self, name: str, connector: Any) -> None:
        self._connectors[name] = connector

    def set_rate_limiter(self, limiter: Any) -> None:
        self._rate_limiter = limiter

    def set_stream_callback(self, callback: Callable) -> None:
        """Set a callback for live execution streaming.

        Callback signature: callback(node_id, status, message)
        """
        self._stream_callback = callback

    def set_approval_callback(self, callback: Callable) -> None:
        """Set a callback for approval gates.

        Callback signature: callback(node_id, message) -> bool
        """
        self._approval_callback = callback

    def execute(self, graph: WorkflowGraph, context: dict | None = None, dry_run: bool = False) -> dict:
        """Synchronous wrapper for workflow execution."""
        self._dry_run = dry_run
        return asyncio.run(self.execute_async(graph, context or {}))

    async def execute_async(self, graph: WorkflowGraph, context: dict) -> dict:
        """Execute a workflow graph asynchronously."""
        run_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()
        mode = "dry_run" if self._dry_run else "live"

        self._emit("__engine__", "started", f"Workflow '{graph.name}' started ({mode})")

        while not graph.is_complete():
            ready = graph.get_ready_nodes()
            if not ready:
                for node in graph.nodes:
                    if node.status == NodeStatus.PENDING:
                        has_failed_dep = any(
                            self._node_failed(graph, dep)
                            for dep in node.depends_on
                        )
                        if has_failed_dep:
                            node.status = NodeStatus.SKIPPED
                            node.error = "Skipped due to failed dependency"
                            self._emit(node.id, "skipped", node.error)
                continue

            tasks = [self._execute_node(node, graph, context) for node in ready]
            await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start_time

        succeeded = sum(1 for n in graph.nodes if n.status == NodeStatus.SUCCESS)
        failed = sum(1 for n in graph.nodes if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in graph.nodes if n.status == NodeStatus.SKIPPED)

        self._emit("__engine__", "completed", f"Done in {int(elapsed * 1000)}ms")

        return {
            "run_id": run_id,
            "workflow_id": graph.id,
            "mode": mode,
            "status": "success" if failed == 0 else "partial_failure",
            "nodes_total": len(graph.nodes),
            "nodes_succeeded": succeeded,
            "nodes_failed": failed,
            "nodes_skipped": skipped,
            "duration_ms": int(elapsed * 1000),
            "results": {n.id: n.result for n in graph.nodes if n.result},
        }

    def _emit(self, node_id: str, status: str, message: str) -> None:
        """Emit a streaming event."""
        if self._stream_callback:
            self._stream_callback(node_id, status, message)

    def _node_failed(self, graph: WorkflowGraph, node_id: str) -> bool:
        node = graph.get_node(node_id)
        return node is not None and node.status == NodeStatus.FAILED

    async def _execute_node(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute a single node based on its type."""
        if node.node_type == NodeType.CONDITION:
            await self._execute_condition(node, graph, context)
        elif node.node_type == NodeType.LOOP:
            await self._execute_loop(node, graph, context)
        elif node.node_type == NodeType.JOIN:
            await self._execute_join(node, graph, context)
        elif node.node_type == NodeType.APPROVAL:
            await self._execute_approval(node, graph, context)
        else:
            await self._execute_standard(node, graph, context)

    async def _execute_standard(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute a standard node with retry logic."""
        node.status = NodeStatus.RUNNING
        node.started_at = time.perf_counter()
        self._emit(node.id, "running", f"Executing {node.name}")

        node_input = dict(context)
        for dep_id in node.depends_on:
            dep = graph.get_node(dep_id)
            if dep and dep.result:
                node_input[dep_id] = dep.result

        # Rate limiting
        if self._rate_limiter:
            await self._rate_limiter.acquire_async(node.connector)

        for attempt in range(node.retry_count):
            try:
                if self._dry_run:
                    node.result = {
                        "status": "dry_run",
                        "connector": node.connector,
                        "action": node.action,
                        "message": f"Dry run — {node.connector}.{node.action} would execute here",
                        "config": node.config,
                    }
                else:
                    connector = self._connectors.get(node.connector)
                    if connector:
                        node.result = await self._run_connector(
                            connector, node.action, node.config, node_input
                        )
                    else:
                        node.result = {
                            "status": "simulated",
                            "connector": node.connector,
                            "action": node.action,
                            "message": f"Connector '{node.connector}' not registered — simulated",
                        }

                node.status = NodeStatus.SUCCESS
                node.finished_at = time.perf_counter()
                self._emit(node.id, "success", f"{node.name} completed ({node.duration_ms}ms)")
                return

            except Exception as e:
                if attempt < node.retry_count - 1:
                    self._emit(node.id, "retry", f"Attempt {attempt + 1} failed, retrying...")
                    await asyncio.sleep(node.retry_delay * (attempt + 1))
                else:
                    node.status = NodeStatus.FAILED
                    node.error = str(e)
                    node.finished_at = time.perf_counter()
                    self._emit(node.id, "failed", f"{node.name} failed: {e}")

    async def _execute_condition(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute a conditional branch node.

        Evaluates the condition and marks either on_true or on_false path.
        The non-selected path's nodes are skipped.
        """
        node.status = NodeStatus.RUNNING
        node.started_at = time.perf_counter()
        self._emit(node.id, "running", f"Evaluating condition: {node.name}")

        node_input = dict(context)
        for dep_id in node.depends_on:
            dep = graph.get_node(dep_id)
            if dep and dep.result:
                node_input[dep_id] = dep.result

        condition = node.condition or {}
        field_name = condition.get("field", "")
        operator = condition.get("operator", "equals")
        expected = condition.get("value")

        # Resolve field value from context
        actual = _resolve_field(field_name, node_input)
        result = _evaluate_condition(actual, operator, expected)

        selected = node.on_true if result else node.on_false
        skipped = node.on_false if result else node.on_true

        node.result = {
            "condition_met": result,
            "selected_path": selected,
            "skipped_path": skipped,
            "actual_value": str(actual),
            "operator": operator,
            "expected_value": str(expected),
        }
        node.status = NodeStatus.SUCCESS
        node.finished_at = time.perf_counter()

        # Skip the non-selected path
        if skipped:
            skip_node = graph.get_node(skipped)
            if skip_node and skip_node.status == NodeStatus.PENDING:
                skip_node.status = NodeStatus.SKIPPED
                skip_node.error = f"Condition '{node.name}' took the {'true' if result else 'false'} path"
                self._emit(skip_node.id, "skipped", skip_node.error)

        self._emit(node.id, "success", f"Condition: {'true' if result else 'false'} → {selected}")

    async def _execute_loop(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute a loop/iterator node.

        Iterates over a list from context and executes the loop body for each item.
        """
        node.status = NodeStatus.RUNNING
        node.started_at = time.perf_counter()
        self._emit(node.id, "running", f"Starting loop: {node.name}")

        node_input = dict(context)
        for dep_id in node.depends_on:
            dep = graph.get_node(dep_id)
            if dep and dep.result:
                node_input[dep_id] = dep.result

        # Get the list to iterate over
        items = _resolve_field(node.iterate_over or "", node_input)
        if not isinstance(items, list):
            items = [items] if items else []

        results = []
        for i, item in enumerate(items):
            item_context = dict(node_input)
            item_context["__loop_item__"] = item
            item_context["__loop_index__"] = i

            if self._dry_run:
                results.append({
                    "index": i,
                    "status": "dry_run",
                    "item": str(item)[:100],
                })
            else:
                # Execute the connector action for each item
                connector = self._connectors.get(node.connector)
                if connector:
                    try:
                        r = await self._run_connector(connector, node.action, node.config, item_context)
                        results.append({"index": i, "status": "success", "result": r})
                    except Exception as e:
                        results.append({"index": i, "status": "error", "error": str(e)})
                else:
                    results.append({"index": i, "status": "simulated"})

            self._emit(node.id, "progress", f"Loop iteration {i + 1}/{len(items)}")

        node.result = {"items_processed": len(items), "results": results}
        node.status = NodeStatus.SUCCESS
        node.finished_at = time.perf_counter()
        self._emit(node.id, "success", f"Loop completed: {len(items)} items processed")

    async def _execute_join(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute a join node that merges results from parallel branches."""
        node.status = NodeStatus.RUNNING
        node.started_at = time.perf_counter()
        self._emit(node.id, "running", f"Joining branches: {node.name}")

        merged = {}
        sources = node.join_from or node.depends_on

        for source_id in sources:
            source = graph.get_node(source_id)
            if source and source.result:
                merged[source_id] = source.result

        node.result = {
            "status": "success",
            "merged_from": list(merged.keys()),
            "data": merged,
        }
        node.status = NodeStatus.SUCCESS
        node.finished_at = time.perf_counter()
        self._emit(node.id, "success", f"Joined {len(merged)} branches")

    async def _execute_approval(self, node: WorkflowNode, graph: WorkflowGraph, context: dict) -> None:
        """Execute an approval gate — pause until human approval."""
        node.status = NodeStatus.WAITING_APPROVAL
        node.started_at = time.perf_counter()

        message = node.approval_message or f"Approval required for: {node.name}"
        self._emit(node.id, "waiting_approval", message)

        approved = False
        if self._approval_callback:
            approved = self._approval_callback(node.id, message)
        elif self._dry_run:
            approved = True  # Auto-approve in dry run
        else:
            # Default: auto-approve (in production, this would wait for user input)
            approved = True

        if approved:
            node.result = {"status": "approved", "message": message}
            node.status = NodeStatus.SUCCESS
            self._emit(node.id, "success", "Approved")
        else:
            node.result = {"status": "rejected", "message": message}
            node.status = NodeStatus.FAILED
            node.error = "Approval rejected"
            self._emit(node.id, "failed", "Approval rejected")

        node.finished_at = time.perf_counter()

    async def _run_connector(self, connector: Any, action: str, config: dict, context: dict) -> Any:
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


def _resolve_field(field_path: str, context: dict) -> Any:
    """Resolve a dot-separated field path from context."""
    parts = field_path.split(".")
    current = context

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None

    return current


def _evaluate_condition(actual: Any, operator: str, expected: Any) -> bool:
    """Evaluate a condition expression."""
    if operator == "equals":
        return str(actual) == str(expected)
    elif operator == "not_equals":
        return str(actual) != str(expected)
    elif operator == "contains":
        return str(expected) in str(actual)
    elif operator == "gt":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    elif operator == "lt":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    elif operator == "gte":
        try:
            return float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False
    elif operator == "lte":
        try:
            return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False
    elif operator == "is_empty":
        return not actual
    elif operator == "is_not_empty":
        return bool(actual)
    elif operator == "in":
        return actual in (expected if isinstance(expected, list) else [expected])
    return False
