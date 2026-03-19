"""FlowPilot CLI — create, run, validate, and manage workflows.

Usage
-----
    python -m flowpilot create "When a new issue is created in GitHub, post to Slack"
    python -m flowpilot run workflow.json
    python -m flowpilot run workflow.json --dry-run
    python -m flowpilot validate workflow.json
    python -m flowpilot list
    python -m flowpilot history
    python -m flowpilot secrets set SLACK_TOKEN xoxb-...
    python -m flowpilot sla
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
    NotificationConnector,
    DatabaseConnector,
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
    run_p.add_argument("--dry-run", action="store_true", help="Simulate execution without making real API calls")

    # validate
    validate_p = subparsers.add_parser("validate", help="Validate a workflow graph")
    validate_p.add_argument("file", help="Workflow JSON file path")

    # list
    subparsers.add_parser("list", help="List saved workflows")

    # history
    history_p = subparsers.add_parser("history", help="Show execution history")
    history_p.add_argument("-n", "--limit", type=int, default=20, help="Number of records")
    history_p.add_argument("--stats", action="store_true", help="Show aggregate statistics")

    # secrets
    secrets_p = subparsers.add_parser("secrets", help="Manage encrypted credentials")
    secrets_sub = secrets_p.add_subparsers(dest="secrets_command")
    secrets_set = secrets_sub.add_parser("set", help="Store a secret")
    secrets_set.add_argument("key", help="Secret name (e.g., SLACK_BOT_TOKEN)")
    secrets_set.add_argument("value", help="Secret value")
    secrets_get = secrets_sub.add_parser("get", help="Retrieve a secret")
    secrets_get.add_argument("key", help="Secret name")
    secrets_sub.add_parser("list", help="List stored secrets")
    secrets_del = secrets_sub.add_parser("delete", help="Delete a secret")
    secrets_del.add_argument("key", help="Secret name")

    # sla
    sla_p = subparsers.add_parser("sla", help="View SLA status and error budgets")
    sla_p.add_argument("--set", nargs=3, metavar=("WORKFLOW_ID", "NAME", "TARGET_PCT"), help="Set SLA target")

    # report
    report_p = subparsers.add_parser("report", help="Generate execution reports")
    report_p.add_argument("type", choices=["summary", "connectors", "sla", "full"], help="Report type")
    report_p.add_argument("--days", type=int, default=7, help="Report period in days (default 7)")
    report_p.add_argument("--format", choices=["markdown", "json", "csv"], default="markdown", help="Output format")
    report_p.add_argument("-o", "--output", help="Export to file path")
    report_p.add_argument("--deliver", choices=["slack", "email", "file"], help="Deliver via channel")
    report_p.add_argument("--channel", help="Delivery target (Slack channel, email address, or file path)")

    # graph
    graph_p = subparsers.add_parser("graph", help="Generate Mermaid diagram for a workflow")
    graph_p.add_argument("file", help="Workflow JSON file path")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start the Gradio dashboard")
    serve_p.add_argument("--port", type=int, default=7860, help="Server port")

    args = parser.parse_args()

    commands = {
        "create": cmd_create,
        "run": cmd_run,
        "validate": cmd_validate,
        "list": cmd_list,
        "history": cmd_history,
        "secrets": cmd_secrets,
        "sla": cmd_sla,
        "report": cmd_report,
        "graph": cmd_graph,
        "serve": cmd_serve,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


def cmd_create(args):
    planner = WorkflowPlanner()
    print(f"Planning workflow: {args.description}")
    print("─" * 50)

    graph = planner.plan(args.description)

    validator = WorkflowValidator()
    errors = validator.validate(graph)
    if errors:
        print(f"\nWarnings ({len(errors)}):")
        for e in errors:
            print(f"  ⚠ {e}")

    print(f"\nWorkflow: {graph.name}")
    print(f"Trigger:  {graph.trigger.get('type', 'manual')}")
    print(f"Nodes:    {len(graph.nodes)}")
    print()

    for i, node in enumerate(graph.nodes, 1):
        deps = f" (after: {', '.join(node.depends_on)})" if node.depends_on else ""
        node_type = f" [{node.node_type.value}]" if node.node_type.value != "standard" else ""
        print(f"  {i}. [{node.connector}.{node.action}]{node_type} {node.name}{deps}")

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
    dry_run = getattr(args, "dry_run", False)

    engine = WorkflowEngine()
    _register_connectors(engine)

    # Live streaming to terminal
    def stream_handler(node_id, status, message):
        icons = {"running": "▶", "success": "✓", "failed": "✗", "skipped": "○",
                 "retry": "↻", "waiting_approval": "⏸", "progress": "…", "started": "●", "completed": "●"}
        icon = icons.get(status, "?")
        print(f"  {icon} [{status}] {message}")

    engine.set_stream_callback(stream_handler)

    mode = " (DRY RUN)" if dry_run else ""
    print(f"Executing: {graph.name}{mode}")
    print(f"Nodes: {len(graph.nodes)}")
    print("─" * 50)

    result = engine.execute(graph, context, dry_run=dry_run)

    history = ExecutionHistory()
    history.record(graph.id, graph.name, result)

    print(f"\n{'─' * 50}")
    print(f"Status: {result['status']} ({result['mode']})")
    print(f"Duration: {result['duration_ms']}ms")
    print(f"Succeeded: {result['nodes_succeeded']}/{result['nodes_total']}")

    if result["nodes_failed"] > 0:
        print(f"Failed: {result['nodes_failed']}")
    if result["nodes_skipped"] > 0:
        print(f"Skipped: {result['nodes_skipped']}")


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


def cmd_secrets(args):
    from flowpilot.secrets import SecretsVault
    vault = SecretsVault()

    if args.secrets_command == "set":
        vault.set(args.key, args.value)
        print(f"✓ Stored: {args.key}")
    elif args.secrets_command == "get":
        value = vault.get(args.key)
        if value:
            print(f"{args.key} = {value}")
        else:
            print(f"Not found: {args.key}")
    elif args.secrets_command == "list":
        keys = vault.list_keys()
        print("Stored Secrets")
        print("─" * 50)
        for k in keys:
            print(f"  {k}")
        if not keys:
            print("  (none)")
    elif args.secrets_command == "delete":
        if vault.delete(args.key):
            print(f"✓ Deleted: {args.key}")
        else:
            print(f"Not found: {args.key}")
    else:
        print("Usage: flowpilot secrets {set|get|list|delete}")


def cmd_sla(args):
    from flowpilot.sla import SLATracker
    tracker = SLATracker()

    if args.set:
        wf_id, name, target = args.set
        tracker.set_target(wf_id, name, float(target))
        print(f"✓ SLA target set: {name} at {target}%")
        return

    statuses = tracker.get_all_statuses()
    if not statuses:
        print("No SLA targets configured. Use: flowpilot sla --set WORKFLOW_ID NAME TARGET_PCT")
        return

    print("SLA Status")
    print("─" * 70)
    for s in statuses:
        icon = {"healthy": "✓", "warning": "⚠", "breached": "✗"}[s.status]
        print(f"  {icon} {s}")

    alerts = tracker.check_alerts()
    if alerts:
        print(f"\nAlerts")
        print("─" * 70)
        for a in alerts:
            print(f"  {a}")


def cmd_report(args):
    from flowpilot.reporting import ReportGenerator
    gen = ReportGenerator()

    report_types = {
        "summary": gen.execution_summary,
        "connectors": gen.connector_usage,
        "sla": gen.sla_compliance,
        "full": gen.full_report,
    }

    report = report_types[args.type](days=args.days)

    # Deliver via channel
    if args.deliver:
        config = {}
        if args.deliver == "slack":
            config["channel"] = args.channel or "#reports"
        elif args.deliver == "email":
            config["to"] = args.channel or ""
        elif args.deliver == "file":
            config["path"] = args.channel or f"reports/{args.type}_report.md"
            config["format"] = args.format

        result = gen.deliver(report, args.deliver, config)
        print(f"Delivered via {args.deliver}: {result}")
        return

    # Export to file
    if args.output:
        gen.export(report, args.output, args.format)
        print(f"Exported to {args.output} ({args.format})")
        return

    # Print to stdout
    if args.format == "json":
        print(report.to_json())
    elif args.format == "csv":
        print(report.to_csv())
    else:
        print(report.to_markdown())


def cmd_graph(args):
    graph = WorkflowGraph.from_file(args.file)
    print(graph.to_mermaid())


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
    engine.register_connector("notification", NotificationConnector())
    engine.register_connector("database", DatabaseConnector())


if __name__ == "__main__":
    main()
