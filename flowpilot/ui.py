"""FlowPilot Gradio Dashboard — visual workflow management UI.

Features: visual graph renderer (Mermaid), live execution streaming,
workflow creation, validation, templates, history, SLA monitoring,
secrets management, and marketplace.

Usage
-----
    pip install gradio
    python -m flowpilot serve
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import gradio as gr

from flowpilot.engine import WorkflowEngine, WorkflowGraph
from flowpilot.planner import WorkflowPlanner
from flowpilot.validator import WorkflowValidator
from flowpilot.history import ExecutionHistory
from flowpilot.rate_limiter import RateLimiter
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


planner = WorkflowPlanner()
validator = WorkflowValidator()
history = ExecutionHistory()
engine = WorkflowEngine()
rate_limiter = RateLimiter()
engine.set_rate_limiter(rate_limiter)

# Register all connectors
for name, cls in [
    ("slack", SlackConnector), ("github", GitHubConnector),
    ("email", EmailConnector), ("http", HttpConnector),
    ("transform", TransformConnector), ("ai", AIConnector),
    ("notification", NotificationConnector), ("database", DatabaseConnector),
]:
    engine.register_connector(name, cls())


# ── Tab Functions ─────────────────────────────────────────────────


def create_workflow(description: str):
    if not description.strip():
        return "", "", "", "Please enter a workflow description."

    graph = planner.plan(description)
    errors = validator.validate(graph)

    visual = f"### {graph.name}\n\n"
    visual += f"**Trigger:** {graph.trigger.get('type', 'manual')}\n\n"
    for i, node in enumerate(graph.nodes, 1):
        deps = f" ← {', '.join(node.depends_on)}" if node.depends_on else ""
        nt = f" `{node.node_type.value}`" if node.node_type.value != "standard" else ""
        visual += f"{i}. **[{node.connector}.{node.action}]**{nt} {node.name}{deps}\n"

    if errors:
        visual += f"\n---\n**Warnings:** {len(errors)}\n"
        for e in errors:
            visual += f"- {e}\n"

    mermaid = f"```mermaid\n{graph.to_mermaid()}\n```"
    return graph.to_json(), visual, mermaid, f"Workflow created with {len(graph.nodes)} nodes."


def execute_workflow(workflow_json: str, dry_run: bool):
    if not workflow_json.strip():
        return "No workflow to execute.", ""

    try:
        graph = WorkflowGraph.from_json(workflow_json)
    except Exception as e:
        return f"Invalid workflow JSON: {e}", ""

    stream_log = []

    def stream_handler(node_id, status, message):
        icons = {"running": "▶", "success": "✅", "failed": "❌", "skipped": "⏭",
                 "retry": "🔄", "waiting_approval": "⏸", "progress": "📊",
                 "started": "🚀", "completed": "🏁"}
        icon = icons.get(status, "ℹ")
        stream_log.append(f"{icon} **[{status}]** {message}")

    engine.set_stream_callback(stream_handler)
    result = engine.execute(graph, {}, dry_run=dry_run)
    history.record(graph.id, graph.name, result)

    mode = "DRY RUN" if dry_run else "LIVE"
    output = f"### Execution Result ({mode})\n\n"
    output += f"**Status:** {result['status']}\n"
    output += f"**Duration:** {result['duration_ms']}ms\n"
    output += f"**Succeeded:** {result['nodes_succeeded']}/{result['nodes_total']}\n\n"

    for node in graph.nodes:
        icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(node.status.value, "⏳")
        duration = f" ({node.duration_ms}ms)" if node.duration_ms else ""
        output += f"{icon} **{node.name}**{duration}\n"
        if node.error:
            output += f"   Error: {node.error}\n"

    # Mermaid with status colours
    mermaid = f"```mermaid\n{graph.to_mermaid()}\n```"
    stream_text = "\n".join(stream_log) if stream_log else "No events captured."

    return output + f"\n---\n### Execution Log\n\n{stream_text}", mermaid


def validate_workflow(workflow_json: str):
    if not workflow_json.strip():
        return "No workflow to validate.", ""

    try:
        graph = WorkflowGraph.from_json(workflow_json)
    except Exception as e:
        return f"Invalid JSON: {e}", ""

    errors = validator.validate(graph)
    mermaid = f"```mermaid\n{graph.to_mermaid()}\n```"

    if errors:
        output = f"### {len(errors)} Issue(s) Found\n\n"
        for e in errors:
            output += f"- ❌ {e}\n"
    else:
        output = "### ✅ Workflow is valid\n\n"
        output += f"**Name:** {graph.name}\n"
        output += f"**Nodes:** {len(graph.nodes)}\n"
        output += f"**Trigger:** {graph.trigger.get('type', 'manual')}"

    return output, mermaid


def load_template(template_name: str):
    templates_dir = Path(__file__).parent.parent / "templates"
    path = templates_dir / f"{template_name}.json"

    if not path.exists():
        return "", "", f"Template '{template_name}' not found."

    graph = WorkflowGraph.from_file(str(path))

    visual = f"### {graph.name}\n\n"
    visual += f"**Description:** {graph.description}\n\n"
    visual += f"**Trigger:** {graph.trigger.get('type', 'manual')}\n\n"
    for i, node in enumerate(graph.nodes, 1):
        deps = f" ← {', '.join(node.depends_on)}" if node.depends_on else ""
        visual += f"{i}. **[{node.connector}.{node.action}]** {node.name}{deps}\n"

    mermaid = f"```mermaid\n{graph.to_mermaid()}\n```"
    return graph.to_json(), visual + f"\n\n{mermaid}", ""


def get_templates_list():
    templates_dir = Path(__file__).parent.parent / "templates"
    if not templates_dir.exists():
        return "No templates directory found."

    output = "### Available Templates\n\n"
    for f in sorted(templates_dir.glob("*.json")):
        try:
            graph = WorkflowGraph.from_file(str(f))
            output += f"- **{f.stem}** — {graph.description} ({len(graph.nodes)} nodes)\n"
        except Exception:
            output += f"- **{f.stem}** — (invalid)\n"
    return output


def get_history_table():
    runs = history.list_runs(limit=20)
    if not runs:
        return "No execution history yet. Run a workflow first."

    output = "### Recent Executions\n\n"
    output += "| Time | Workflow | Status | Duration | Nodes |\n"
    output += "|------|----------|--------|----------|-------|\n"
    for run in runs:
        output += (
            f"| {run.started_at[:19]} | {run.workflow_name} | {run.status} "
            f"| {run.duration_ms}ms | {run.nodes_succeeded}/{run.nodes_total} |\n"
        )
    return output


def get_history_stats():
    stats = history.get_stats()
    if stats["total_runs"] == 0:
        return "No execution history yet."

    return (
        f"### Execution Statistics\n\n"
        f"- **Total runs:** {stats['total_runs']}\n"
        f"- **Success rate:** {stats['success_rate']}%\n"
        f"- **Avg duration:** {stats['avg_duration_ms']}ms\n"
        f"- **Min duration:** {stats['min_duration_ms']}ms\n"
        f"- **Max duration:** {stats['max_duration_ms']}ms\n"
    )


def get_rate_limit_stats():
    stats = rate_limiter.get_all_stats()
    if not stats:
        return "No rate limits configured."

    output = "### Rate Limiter Status\n\n"
    output += "| Connector | Limit | Window | Usage | Remaining | Throttled |\n"
    output += "|-----------|-------|--------|-------|-----------|-----------|\n"
    for s in stats:
        output += (
            f"| {s['connector']} | {s['limit']} | {s['window_seconds']}s "
            f"| {s['current_usage']} | {s['remaining']} | {s['total_throttled']} |\n"
        )
    return output


def get_sla_status():
    from flowpilot.sla import SLATracker
    tracker = SLATracker()
    statuses = tracker.get_all_statuses()
    if not statuses:
        return "No SLA targets configured."

    output = "### SLA Status\n\n"
    output += "| Workflow | Target | Current | Budget | Status |\n"
    output += "|----------|--------|---------|--------|--------|\n"
    for s in statuses:
        icon = {"healthy": "🟢", "warning": "🟡", "breached": "🔴"}[s.status]
        output += (
            f"| {s.workflow_name} | {s.sla_target}% | {s.current_rate}% "
            f"| {s.error_budget_pct:.0f}% | {icon} {s.status} |\n"
        )

    alerts = tracker.check_alerts()
    if alerts:
        output += "\n### Alerts\n\n"
        for a in alerts:
            output += f"- ⚠ {a}\n"

    return output


def save_workflow(workflow_json: str, name: str):
    if not workflow_json.strip() or not name.strip():
        return "Provide both a workflow and a name."

    workflows_dir = Path("workflows")
    workflows_dir.mkdir(exist_ok=True)
    path = workflows_dir / f"{name}.json"
    path.write_text(workflow_json)

    # Auto-version
    from flowpilot.versioning import WorkflowVersionStore
    store = WorkflowVersionStore()
    data = json.loads(workflow_json)
    ver = store.save_version(data.get("id", name), data.get("name", name), data, message=f"Saved from dashboard")

    return f"Saved to {path} (version {ver})"


# ── Build Gradio App ──────────────────────────────────────────────


def create_app() -> gr.Blocks:
    templates_dir = Path(__file__).parent.parent / "templates"
    template_names = [f.stem for f in templates_dir.glob("*.json")] if templates_dir.exists() else []

    with gr.Blocks(
        title="FlowPilot",
        theme=gr.themes.Soft(primary_hue="blue"),
        css=".gradio-container { max-width: 1200px !important; }",
    ) as app:

        gr.Markdown("# FlowPilot\n*Describe workflows in plain English. FlowPilot wires up the APIs.*")

        with gr.Tabs():

            # ── Create Tab ──
            with gr.Tab("Create Workflow"):
                description_input = gr.Textbox(
                    label="Describe your workflow",
                    placeholder='e.g., "When a new GitHub issue is created, summarise it with AI and post to Slack #dev"',
                    lines=3,
                )
                create_btn = gr.Button("Create Workflow", variant="primary")

                with gr.Row():
                    with gr.Column():
                        workflow_visual = gr.Markdown(label="Workflow Preview")
                    with gr.Column():
                        graph_preview = gr.Markdown(label="Graph Diagram")

                workflow_json = gr.Code(label="Workflow JSON", language="json")
                status_msg = gr.Textbox(label="Status", interactive=False)

                create_btn.click(
                    fn=create_workflow,
                    inputs=description_input,
                    outputs=[workflow_json, workflow_visual, graph_preview, status_msg],
                )

                with gr.Row():
                    save_name = gr.Textbox(label="Save as", placeholder="my-workflow")
                    save_btn = gr.Button("Save", size="sm")
                    save_status = gr.Textbox(label="", interactive=False)

                save_btn.click(
                    fn=save_workflow,
                    inputs=[workflow_json, save_name],
                    outputs=save_status,
                )

            # ── Execute Tab ──
            with gr.Tab("Execute"):
                exec_json = gr.Code(label="Workflow JSON", language="json")
                with gr.Row():
                    dry_run_toggle = gr.Checkbox(label="Dry Run (simulate without real API calls)", value=False)
                    exec_btn = gr.Button("Execute", variant="primary")

                with gr.Row():
                    with gr.Column():
                        exec_result = gr.Markdown()
                    with gr.Column():
                        exec_graph = gr.Markdown(label="Execution Graph")

                exec_btn.click(
                    fn=execute_workflow,
                    inputs=[exec_json, dry_run_toggle],
                    outputs=[exec_result, exec_graph],
                )

            # ── Validate Tab ──
            with gr.Tab("Validate"):
                val_json = gr.Code(label="Workflow JSON", language="json")
                val_btn = gr.Button("Validate", variant="primary")
                with gr.Row():
                    with gr.Column():
                        val_result = gr.Markdown()
                    with gr.Column():
                        val_graph = gr.Markdown()
                val_btn.click(fn=validate_workflow, inputs=val_json, outputs=[val_result, val_graph])

            # ── Templates Tab ──
            with gr.Tab("Templates"):
                templates_list = gr.Markdown(value=get_templates_list())
                if template_names:
                    template_select = gr.Dropdown(choices=template_names, label="Load Template")
                    load_btn = gr.Button("Load", size="sm")
                    template_preview = gr.Markdown()
                    template_json = gr.Code(label="Template JSON", language="json")
                    template_status = gr.Textbox(label="", interactive=False, visible=False)
                    load_btn.click(
                        fn=load_template,
                        inputs=template_select,
                        outputs=[template_json, template_preview, template_status],
                    )

            # ── History Tab ──
            with gr.Tab("History"):
                refresh_btn = gr.Button("Refresh", size="sm")
                history_md = gr.Markdown()
                stats_md = gr.Markdown()
                refresh_btn.click(fn=get_history_table, outputs=history_md)
                refresh_btn.click(fn=get_history_stats, outputs=stats_md)

            # ── SLA / Rate Limits Tab ──
            with gr.Tab("Monitoring"):
                gr.Markdown("### SLA and Rate Limit Monitoring")
                mon_refresh = gr.Button("Refresh", size="sm")
                sla_md = gr.Markdown()
                rate_md = gr.Markdown()
                mon_refresh.click(fn=get_sla_status, outputs=sla_md)
                mon_refresh.click(fn=get_rate_limit_stats, outputs=rate_md)

            # ── Connectors Tab ──
            with gr.Tab("Connectors"):
                gr.Markdown("""### Available Connectors

| Connector | Actions | Auth |
|-----------|---------|------|
| **slack** | send_message, read_channel, create_channel | SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL |
| **github** | get_issues, get_pull_requests, create_issue, create_comment | GITHUB_TOKEN |
| **email** | send_email, read_inbox | EMAIL_USERNAME + EMAIL_PASSWORD |
| **http** | get, post, put, delete | Per-request headers |
| **transform** | filter, map, format_template, extract_field, join | None |
| **ai** | summarise, classify, extract, generate | ANTHROPIC_API_KEY |
| **notification** | send_notification (desktop, sms, webhook) | TWILIO_* for SMS |
| **database** | query, insert, update | DATABASE_URL |

Set environment variables or use `flowpilot secrets set` to enable real API calls.
Without credentials, connectors run in simulation mode.

### Node Types

| Type | Description |
|------|-------------|
| **standard** | Normal connector execution |
| **condition** | If/else branching based on field evaluation |
| **loop** | Iterate over a list, executing per item |
| **join** | Merge results from parallel branches |
| **approval** | Human-in-the-loop gate — pause until approved |
""")

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860)
