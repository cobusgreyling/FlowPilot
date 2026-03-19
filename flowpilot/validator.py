"""Workflow graph validator.

Checks workflow graphs for structural issues before execution:
cycles, missing dependencies, invalid connectors, empty configs,
conditional branching integrity, loop references, and join nodes.
"""

from __future__ import annotations

from flowpilot.engine import WorkflowGraph, NodeType


KNOWN_CONNECTORS = {
    "slack": ["send_message", "read_channel", "create_channel"],
    "github": ["create_issue", "get_issues", "create_comment", "get_pull_requests", "merge_pr"],
    "email": ["send_email", "read_inbox"],
    "http": ["get", "post", "put", "delete"],
    "transform": ["filter", "map", "format_template", "extract_field", "join"],
    "ai": ["summarise", "classify", "extract", "generate"],
    "file": ["read", "write", "append"],
    "database": ["query", "insert", "update"],
    "schedule": ["delay", "wait_until"],
    "notification": ["send_notification"],
}


class WorkflowValidator:
    """Validates workflow graphs for structural correctness."""

    def validate(self, graph: WorkflowGraph) -> list[str]:
        """Run all validation checks. Returns a list of error messages."""
        errors = []
        errors.extend(self._check_empty(graph))
        errors.extend(self._check_duplicate_ids(graph))
        errors.extend(self._check_missing_dependencies(graph))
        errors.extend(self._check_cycles(graph))
        errors.extend(self._check_connectors(graph))
        errors.extend(self._check_trigger(graph))
        errors.extend(self._check_conditions(graph))
        errors.extend(self._check_loops(graph))
        errors.extend(self._check_joins(graph))
        errors.extend(self._check_approvals(graph))
        return errors

    def _check_empty(self, graph: WorkflowGraph) -> list[str]:
        if not graph.nodes:
            return ["Workflow has no nodes"]
        return []

    def _check_duplicate_ids(self, graph: WorkflowGraph) -> list[str]:
        seen = set()
        errors = []
        for node in graph.nodes:
            if node.id in seen:
                errors.append(f"Duplicate node ID: '{node.id}'")
            seen.add(node.id)
        return errors

    def _check_missing_dependencies(self, graph: WorkflowGraph) -> list[str]:
        node_ids = {n.id for n in graph.nodes}
        errors = []
        for node in graph.nodes:
            for dep in node.depends_on:
                if dep not in node_ids:
                    errors.append(
                        f"Node '{node.id}' depends on '{dep}' which does not exist"
                    )
        return errors

    def _check_cycles(self, graph: WorkflowGraph) -> list[str]:
        """Detect cycles using DFS."""
        adjacency = {n.id: n.depends_on for n in graph.nodes}
        visited = set()
        in_stack = set()
        errors = []

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for dep in adjacency.get(node_id, []):
                if dep in in_stack:
                    errors.append(f"Cycle detected involving node '{node_id}' and '{dep}'")
                    return True
                if dep not in visited:
                    if dfs(dep):
                        return True
            in_stack.discard(node_id)
            return False

        for node in graph.nodes:
            if node.id not in visited:
                dfs(node.id)

        return errors

    def _check_connectors(self, graph: WorkflowGraph) -> list[str]:
        errors = []
        for node in graph.nodes:
            if not node.connector and node.node_type in (NodeType.CONDITION, NodeType.JOIN, NodeType.APPROVAL):
                continue  # Control flow nodes may not need connectors
            if node.connector in KNOWN_CONNECTORS:
                valid_actions = KNOWN_CONNECTORS[node.connector]
                if node.action and node.action not in valid_actions:
                    errors.append(
                        f"Node '{node.id}': unknown action '{node.action}' "
                        f"for connector '{node.connector}'. "
                        f"Valid actions: {', '.join(valid_actions)}"
                    )
        return errors

    def _check_trigger(self, graph: WorkflowGraph) -> list[str]:
        errors = []
        if graph.trigger:
            trigger_type = graph.trigger.get("type")
            valid_types = {"cron", "webhook", "manual", "event"}
            if trigger_type and trigger_type not in valid_types:
                errors.append(
                    f"Unknown trigger type: '{trigger_type}'. "
                    f"Valid types: {', '.join(valid_types)}"
                )
            if trigger_type == "cron":
                config = graph.trigger.get("config", {})
                if not config.get("schedule"):
                    errors.append("Cron trigger requires a 'schedule' in config")
        return errors

    def _check_conditions(self, graph: WorkflowGraph) -> list[str]:
        """Validate conditional branch nodes."""
        errors = []
        node_ids = {n.id for n in graph.nodes}
        for node in graph.nodes:
            if node.node_type == NodeType.CONDITION:
                if not node.condition:
                    errors.append(f"Condition node '{node.id}' has no condition defined")
                if node.on_true and node.on_true not in node_ids:
                    errors.append(f"Condition '{node.id}' on_true references '{node.on_true}' which does not exist")
                if node.on_false and node.on_false not in node_ids:
                    errors.append(f"Condition '{node.id}' on_false references '{node.on_false}' which does not exist")
                if not node.on_true and not node.on_false:
                    errors.append(f"Condition '{node.id}' has neither on_true nor on_false path defined")
        return errors

    def _check_loops(self, graph: WorkflowGraph) -> list[str]:
        """Validate loop/iterator nodes."""
        errors = []
        for node in graph.nodes:
            if node.node_type == NodeType.LOOP:
                if not node.iterate_over:
                    errors.append(f"Loop node '{node.id}' has no iterate_over field")
                if not node.connector and not node.loop_body:
                    errors.append(f"Loop node '{node.id}' needs either a connector/action or a loop_body reference")
        return errors

    def _check_joins(self, graph: WorkflowGraph) -> list[str]:
        """Validate join nodes."""
        errors = []
        node_ids = {n.id for n in graph.nodes}
        for node in graph.nodes:
            if node.node_type == NodeType.JOIN:
                sources = node.join_from or node.depends_on
                if len(sources) < 2:
                    errors.append(f"Join node '{node.id}' should merge at least 2 branches")
                for src in node.join_from:
                    if src not in node_ids:
                        errors.append(f"Join node '{node.id}' references '{src}' which does not exist")
        return errors

    def _check_approvals(self, graph: WorkflowGraph) -> list[str]:
        """Validate approval gate nodes."""
        errors = []
        for node in graph.nodes:
            if node.node_type == NodeType.APPROVAL:
                if not node.approval_message and not node.name:
                    errors.append(f"Approval node '{node.id}' has no message or name")
        return errors
