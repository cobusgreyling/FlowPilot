"""FlowPilot CLI — create, run, validate, and manage workflows.

Usage
-----
    python -m flowpilot create "When a new issue is created in GitHub, post to Slack"
    python -m flowpilot run workflow.json
    python -m flowpilot validate workflow.json
    python -m flowpilot list
    python -m flowpilot history
    python -m flowpilot serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from flowpilot.engine import WorkflowEngine, WorkflowGraph
from flowpilot.planner import WorkflowPlanner
from flowpilot.validator import WorkflowValidator
from flowpilot.history import ExecutionHistory
from flowpilot.connectors import (
    SlackConnector,
    GitHubConnector,
    EmailConnector,
    HttpConnector,
    TransformConnector,
    AIConnector,
)


def main():
    parser = argparse.ArgumentParser(
        prog="flowpilot",
        description="FlowPilot — AI-Powered Workflow Automation",
    )
    subparsers = parser.add_subparsers(dest="command")

    # create
    create_p = subparsers.add_parser("create", help="Create a workflow from natural language")
    create_p.add_argument("description", help="Workflow description in plain English")
    create_p.add_argument("-o", "--output", help="Output file path (default: stdout)")
    create_p.add_argument("--save", help="Save to workflows/ directory with this name")

    # run
    run_p = subparsers.add_parser("run", help="Execute a workflow from a JSON file")
    run_p.add_argument("file", help="Workflow JSON file path")
    run_p.add_argument("--context", help="JSON string of context variables")

    # validate
    validate_p = subparsers.add_parser("validate", help="Validate a workflow graph")
    validate_p.add_argument("file", help="Workflow JSON file path")

    # list
    subparsers.add_parser("list", help="List saved workflows")

    # history
    history_p = subparsers.add_parser("history", help="Show execution history")
    history_p.add_argument("-n", "--limit", type=int, default=20, help="Number of records")
    history_p.add_argument("--stats", action="store_true", help="Show aggregate statistics")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start the Gradio dashboard")
    serve_p.add_argument("--port", type=int, default=7860, help="Server port")

    args = parser.parse_args()

    if args.command == "create":
        cmd_create(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "list":
        cmd_list()
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


def cmd_create(args):
    planner = WorkflowPlanner()
    print(f"Planning workflow: {args.description}")
    print("─" * 50)

    graph = planner.plan(args.description)

    # Validate
    validator = WorkflowValidator()
    errors = validator.validate(graph)
    if errors:
        print(f"\nWarnings ({len(errors)}):")
        for e in errors:
            print(f"  ⚠ {e}")

    # Display
    print(f"\nWorkflow: {graph.name}")
    print(f"Trigger:  {graph.trigger.get('type', 'manual')}")
    print(f"Nodes:    {len(graph.nodes)}")
    print()

    for i, node in enumerate(graph.nodes, 1):
        deps = f" (after: {', '.join(node.depends_on)})" if node.depends_on else ""
        print(f"  {i}. [{node.connector}.{node.action}] {node.name}{deps}")

    # Output
    output = graph.to_json()
    if args.output:
        Path(args.output).write_text(output)
        print(f"\nSaved to {args.output}")
    elif args.save:
        workflows_dir = Path("workflows")
        workflows_dir.mkdir(exist_ok=True)
        path = workflows_dir / f"{args.save}.json"
        path.write_text(output)
        print(f"\nSaved to {path}")
    else:
        print(f"\n{output}")


def cmd_run(args):
    graph = WorkflowGraph.from_file(args.file)
    context = json.loads(args.context) if args.context else {}

    engine = WorkflowEngine()
    _register_connectors(engine)

    print(f"Executing: {graph.name}")
    print(f"Nodes: {len(graph.nodes)}")
    print("─" * 50)

    result = engine.execute(graph, context)

    # Record in history
    history = ExecutionHistory()
    history.record(graph.id, graph.name, result)

    # Display results
    print(f"\nStatus: {result['status']}")
    print(f"Duration: {result['duration_ms']}ms")
    print(f"Succeeded: {result['nodes_succeeded']}/{result['nodes_total']}")

    if result["nodes_failed"] > 0:
        print(f"Failed: {result['nodes_failed']}")

    print("\nNode results:")
    for node in graph.nodes:
        status_icon = {"success": "✓", "failed": "✗", "skipped": "○"}.get(node.status.value, "?")
        duration = f" ({node.duration_ms}ms)" if node.duration_ms else ""
        print(f"  {status_icon} {node.name}{duration}")
        if node.error:
            print(f"    Error: {node.error}")


def cmd_validate(args):
    graph = WorkflowGraph.from_file(args.file)
    validator = WorkflowValidator()
    errors = validator.validate(graph)

    print(f"Validating: {args.file}")
    print(f"Workflow: {graph.name}")
    print(f"Nodes: {len(graph.nodes)}")
    print("─" * 50)

    if errors:
        print(f"\n{len(errors)} issue(s) found:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("\n✓ Workflow is valid")


def cmd_list():
    workflows_dir = Path("workflows")
    templates_dir = Path("templates")

    print("Saved Workflows")
    print("─" * 50)
    if workflows_dir.exists():
        for f in sorted(workflows_dir.glob("*.json")):
            graph = WorkflowGraph.from_file(str(f))
            print(f"  {f.stem}: {graph.name} ({len(graph.nodes)} nodes)")
    else:
        print("  No saved workflows")

    print(f"\nTemplates")
    print("─" * 50)
    if templates_dir.exists():
        for f in sorted(templates_dir.glob("*.json")):
            graph = WorkflowGraph.from_file(str(f))
            print(f"  {f.stem}: {graph.name} ({len(graph.nodes)} nodes)")
    else:
        print("  No templates found")


def cmd_history(args):
    history = ExecutionHistory()

    if args.stats:
        stats = history.get_stats()
        print("Execution Statistics")
        print("─" * 50)
        print(f"  Total runs:     {stats['total_runs']}")
        print(f"  Successes:      {stats['successes']}")
        print(f"  Failures:       {stats['failures']}")
        print(f"  Success rate:   {stats['success_rate']}%")
        print(f"  Avg duration:   {stats['avg_duration_ms']}ms")
        print(f"  Min duration:   {stats['min_duration_ms']}ms")
        print(f"  Max duration:   {stats['max_duration_ms']}ms")
        return

    runs = history.list_runs(limit=args.limit)
    print("Execution History")
    print("─" * 50)
    if runs:
        for run in runs:
            print(f"  {run}")
    else:
        print("  No execution history")


def cmd_serve(args):
    try:
        from flowpilot.ui import create_app
        app = create_app()
        app.launch(server_name="0.0.0.0", server_port=args.port)
    except ImportError:
        print("Gradio not installed. Install with: pip install gradio")
        sys.exit(1)


def _register_connectors(engine: WorkflowEngine) -> None:
    engine.register_connector("slack", SlackConnector())
    engine.register_connector("github", GitHubConnector())
    engine.register_connector("email", EmailConnector())
    engine.register_connector("http", HttpConnector())
    engine.register_connector("transform", TransformConnector())
    engine.register_connector("ai", AIConnector())


if __name__ == "__main__":
    main()
