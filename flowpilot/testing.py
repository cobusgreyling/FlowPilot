"""Workflow testing framework for validating workflows before deployment."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .engine import WorkflowEngine, WorkflowGraph, WorkflowNode, NodeStatus


@dataclass
class NodeTest:
    node_id: str
    mock_inputs: dict = field(default_factory=dict)
    expected_status: str = "success"
    expected_output_contains: Optional[dict] = None
    timeout: float = 30.0


@dataclass
class WorkflowTest:
    workflow_path: str
    node_tests: list[NodeTest] = field(default_factory=list)
    expected_final_status: str = "success"
    description: str = ""


@dataclass
class TestResult:
    node_id: str
    passed: bool
    expected: str
    actual: str
    error: Optional[str] = None
    duration_ms: float = 0.0


class WorkflowTestRunner:
    """Run tests against workflows with mocked connector responses."""

    def __init__(self, engine: WorkflowEngine):
        self.engine = engine
        self._mocks: dict[str, Any] = {}

    def test_node(self, node: WorkflowNode, mock_config: dict = None, mock_context: dict = None) -> TestResult:
        start = time.time()
        try:
            connector = self.engine._connectors.get(node.connector)
            if not connector:
                return TestResult(node_id=node.id, passed=False, expected="connector found",
                                  actual=f"connector '{node.connector}' not registered",
                                  duration_ms=(time.time() - start) * 1000)
            action_fn = getattr(connector, node.action, None)
            if not action_fn:
                return TestResult(node_id=node.id, passed=False, expected="action found",
                                  actual=f"action '{node.action}' not found",
                                  duration_ms=(time.time() - start) * 1000)
            config = mock_config or node.config or {}
            context = mock_context or {}
            result = action_fn(config, context)
            duration = (time.time() - start) * 1000
            return TestResult(node_id=node.id, passed=True, expected="success", actual="success", duration_ms=duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            return TestResult(node_id=node.id, passed=False, expected="success", actual=str(e),
                              error=str(e), duration_ms=duration)

    def test_workflow(self, workflow_graph: WorkflowGraph, node_mocks: dict = None) -> list[TestResult]:
        results = []
        original_execute = {}

        # Patch connectors with mocks
        if node_mocks:
            for node_id, mock_response in node_mocks.items():
                for node in workflow_graph.nodes:
                    if node.id == node_id:
                        connector = self.engine._connectors.get(node.connector)
                        if connector:
                            original_fn = getattr(connector, node.action, None)
                            if original_fn:
                                original_execute[(node.connector, node.action)] = original_fn
                                setattr(connector, node.action, lambda c, ctx, r=mock_response: r)

        try:
            result = self.engine.execute(workflow_graph, dry_run=True)
            for node in workflow_graph.nodes:
                node_result = result.get("results", {}).get(node.id)
                status = node.status.value if hasattr(node.status, 'value') else str(node.status)
                passed = status in ("success", "skipped")
                results.append(TestResult(
                    node_id=node.id, passed=passed,
                    expected="success", actual=status,
                    duration_ms=result.get("duration_ms", 0) / max(len(workflow_graph.nodes), 1),
                ))
        except Exception as e:
            results.append(TestResult(node_id="workflow", passed=False, expected="success", actual=str(e), error=str(e)))
        finally:
            # Restore original functions
            for (conn_name, action_name), original_fn in original_execute.items():
                connector = self.engine._connectors.get(conn_name)
                if connector:
                    setattr(connector, action_name, original_fn)

        return results

    def test_connections(self, workflow_graph: WorkflowGraph) -> list[TestResult]:
        results = []
        tested = set()
        for node in workflow_graph.nodes:
            if node.connector in tested:
                continue
            tested.add(node.connector)
            connector = self.engine._connectors.get(node.connector)
            if connector:
                results.append(TestResult(
                    node_id=f"connection:{node.connector}", passed=True,
                    expected="registered", actual="registered",
                ))
            else:
                results.append(TestResult(
                    node_id=f"connection:{node.connector}", passed=False,
                    expected="registered", actual="not found",
                ))
        return results

    def run_suite(self, test_suite: WorkflowTest) -> list[TestResult]:
        graph = WorkflowGraph.from_file(test_suite.workflow_path)
        results = []

        # Connection tests
        results.extend(self.test_connections(graph))

        # Individual node tests
        node_map = {n.id: n for n in graph.nodes}
        mocks = {}
        for node_test in test_suite.node_tests:
            if node_test.mock_inputs:
                mocks[node_test.node_id] = node_test.mock_inputs

        # Full workflow test
        workflow_results = self.test_workflow(graph, node_mocks=mocks)
        results.extend(workflow_results)

        return results

    def generate_test_template(self, workflow_graph: WorkflowGraph) -> WorkflowTest:
        node_tests = []
        for node in workflow_graph.nodes:
            node_tests.append(NodeTest(
                node_id=node.id,
                mock_inputs={"mock": True},
                expected_status="success",
            ))
        return WorkflowTest(
            workflow_path="",
            node_tests=node_tests,
            expected_final_status="success",
            description=f"Auto-generated test for: {workflow_graph.name}",
        )


class TestReport:
    """Format test results as a readable report."""

    @staticmethod
    def format(results: list[TestResult], title: str = "Test Results") -> str:
        lines = [f"## {title}", ""]
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        lines.append(f"**{passed}/{total} passed** {'✅' if passed == total else '❌'}")
        lines.append("")
        lines.append("| Node | Status | Expected | Actual | Duration |")
        lines.append("|------|--------|----------|--------|----------|")
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            icon = "✅" if r.passed else "❌"
            lines.append(f"| {r.node_id} | {icon} {status} | {r.expected} | {r.actual} | {r.duration_ms:.1f}ms |")
        if any(r.error for r in results):
            lines.append("")
            lines.append("### Errors")
            for r in results:
                if r.error:
                    lines.append(f"- **{r.node_id}**: {r.error}")
        return "\n".join(lines)
