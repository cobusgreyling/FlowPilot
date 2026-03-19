"""FlowPilot — AI-Powered Workflow Automation."""

from flowpilot.engine import WorkflowEngine, WorkflowNode, WorkflowGraph
from flowpilot.planner import WorkflowPlanner
from flowpilot.validator import WorkflowValidator
from flowpilot.history import ExecutionHistory
from flowpilot.connectors.base import BaseConnector

__version__ = "0.1.0"


class FlowPilot:
    """Main entry point for the FlowPilot SDK."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self.engine = WorkflowEngine()
        self.planner = WorkflowPlanner()
        self.validator = WorkflowValidator()
        self.history = ExecutionHistory(db_path)

    def create(self, description: str) -> WorkflowGraph:
        """Create a workflow from a natural language description."""
        graph = self.planner.plan(description)
        errors = self.validator.validate(graph)
        if errors:
            print(f"Warning: {len(errors)} validation issue(s) found")
            for e in errors:
                print(f"  - {e}")
        return graph

    def run(self, graph: WorkflowGraph, context: dict | None = None) -> dict:
        """Execute a workflow graph."""
        return self.engine.execute(graph, context or {})

    def validate(self, graph: WorkflowGraph) -> list[str]:
        """Validate a workflow graph without executing it."""
        return self.validator.validate(graph)
