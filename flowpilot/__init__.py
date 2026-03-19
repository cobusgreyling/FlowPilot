"""FlowPilot — AI-Powered Workflow Automation."""

from flowpilot.engine import WorkflowEngine, WorkflowNode, WorkflowGraph, NodeType, NodeStatus
from flowpilot.planner import WorkflowPlanner
from flowpilot.validator import WorkflowValidator
from flowpilot.history import ExecutionHistory
from flowpilot.secrets import SecretsVault
from flowpilot.versioning import WorkflowVersionStore
from flowpilot.sla import SLATracker
from flowpilot.rate_limiter import RateLimiter
from flowpilot.marketplace import WorkflowMarketplace
from flowpilot.connectors.base import BaseConnector

__version__ = "0.2.0"


class FlowPilot:
    """Main entry point for the FlowPilot SDK."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self.engine = WorkflowEngine()
        self.planner = WorkflowPlanner()
        self.validator = WorkflowValidator()
        self.history = ExecutionHistory(db_path)
        self.versions = WorkflowVersionStore(db_path)
        self.sla = SLATracker(db_path)
        self.rate_limiter = RateLimiter()
        self.marketplace = WorkflowMarketplace(db_path)

        self.engine.set_rate_limiter(self.rate_limiter)

    def create(self, description: str) -> WorkflowGraph:
        """Create a workflow from a natural language description."""
        graph = self.planner.plan(description)
        errors = self.validator.validate(graph)
        if errors:
            print(f"Warning: {len(errors)} validation issue(s) found")
            for e in errors:
                print(f"  - {e}")
        return graph

    def run(self, graph: WorkflowGraph, context: dict | None = None, dry_run: bool = False) -> dict:
        """Execute a workflow graph."""
        result = self.engine.execute(graph, context or {}, dry_run=dry_run)
        self.history.record(graph.id, graph.name, result)
        self.versions.save_version(graph.id, graph.name, graph.to_dict(), message="Executed")
        return result

    def validate(self, graph: WorkflowGraph) -> list[str]:
        """Validate a workflow graph without executing it."""
        return self.validator.validate(graph)

    def dry_run(self, graph: WorkflowGraph, context: dict | None = None) -> dict:
        """Execute in dry run mode — simulate without real API calls."""
        return self.run(graph, context, dry_run=True)
