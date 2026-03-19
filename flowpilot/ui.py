"""FlowPilot Gradio Dashboard — visual workflow management UI.

Provides a web interface for creating workflows from natural language,
viewing workflow graphs, executing workflows, browsing templates,
and reviewing execution history.

Usage
-----
    pip install gradio
    python -m flowpilot serve
"""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

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


planner = WorkflowPlanner()
validator = WorkflowValidator()
history = ExecutionHistory()
engine = WorkflowEngine()

# Register connectors
engine.register_connector("slack", SlackConnector())
engine.register_connector("github", GitHubConnector())
engine.register_connector("email", EmailConnector())
engine.register_connector("http", HttpConnector())
engine.register_connector("transform", TransformConnector())
engine.register_connector("ai", AIConnector())


# ── Tab Functions ─────────────────────────────────────────────────


def create_workflow(description: str):
    """Create a workflow from natural language."""
    if not description.strip():
        return "", "", "Please enter a workflow description."

    graph = planner.plan(description)
    errors = validator.validate(graph)

    # Build visual representation
    visual = f"### {graph.name}\n\n"
    visual += f"**Trigger:** {graph.trigger.get('type', 'manual')}\n\n"

    for i, node in enumerate(graph.nodes, 1):
        deps = f" ← {', '.join(node.depends_on)}" if node.depends_on else ""
        visual += f"{i}. **[{node.connector}.{node.action}]** {node.name}{deps}\n"

    if errors:
        visual += f"\n---\n**Warnings:** {len(errors)}\n"
        for e in errors:
            visual += f"- {e}\n"

    return graph.to_json(), visual, f"Workflow created with {len(graph.nodes)} nodes."


def execute_workflow(workflow_json: str):
    """Execute a workflow from JSON."""
    if not workflow_json.strip():
        return "No workflow to execute."

    try:
        graph = WorkflowGraph.from_json(workflow_json)
    except Exception as e:
        return f"Invalid workflow JSON: {e}"

    result = engine.execute(graph, {})
    history.record(graph.id, graph.name, result)

    output = f"### Execution Result\n\n"
    output += f"**Status:** {result['status']}\n"
    output += f"**Duration:** {result['duration_ms']}ms\n"
    output += f"**Succeeded:** {result['nodes_succeeded']}/{result['nodes_total']}\n\n"

    for node in graph.nodes:
        icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(node.status.value, "⏳")
        duration = f" ({node.duration_ms}ms)" if node.duration_ms else ""
        output += f"{icon} **{node.name}**{duration}\n"
        if node.error:
            output += f"   Error: {node.error}\n"

    return output


def validate_workflow(workflow_json: str):
    """Validate a workflow graph."""
    if not workflow_json.strip():
        return "No workflow to validate."

    try:
        graph = WorkflowGraph.from_json(workflow_json)
    except Exception as e:
        return f"Invalid JSON: {e}"

    errors = validator.validate(graph)

    if errors:
        output = f"### {len(errors)} Issue(s) Found\n\n"
        for e in errors:
            output += f"- ❌ {e}\n"
    else:
        output = "### ✅ Workflow is valid\n\n"
        output += f"**Name:** {graph.name}\n"
        output += f"**Nodes:** {len(graph.nodes)}\n"
        output += f"**Trigger:** {graph.trigger.get('type', 'manual')}"

    return output


def load_template(template_name: str):
    """Load a workflow template."""
    templates_dir = Path(__file__).parent.parent / "templates"
    path = templates_dir / f"{template_name}.json"

    if not path.exists():
        return "", f"Template '{template_name}' not found."

    graph = WorkflowGraph.from_file(str(path))

    visual = f"### {graph.name}\n\n"
    visual += f"**Description:** {graph.description}\n\n"
    visual += f"**Trigger:** {graph.trigger.get('type', 'manual')}\n\n"
    for i, node in enumerate(graph.nodes, 1):
        deps = f" ← {', '.join(node.depends_on)}" if node.depends_on else ""
        visual += f"{i}. **[{node.connector}.{node.action}]** {node.name}{deps}\n"

    return graph.to_json(), visual


def get_templates_list():
    """List available templates."""
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
    """Get execution history as markdown."""
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
    """Get aggregate execution statistics."""
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


def save_workflow(workflow_json: str, name: str):
    """Save a workflow to the workflows directory."""
    if not workflow_json.strip() or not name.strip():
        return "Provide both a workflow and a name."

    workflows_dir = Path("workflows")
    workflows_dir.mkdir(exist_ok=True)
    path = workflows_dir / f"{name}.json"
    path.write_text(workflow_json)
    return f"Saved to {path}"


# ── Build Gradio App ──────────────────────────────────────────────


def create_app() -> gr.Blocks:
    templates_dir = Path(__file__).parent.parent / "templates"
    template_names = [f.stem for f in templates_dir.glob("*.json")] if templates_dir.exists() else []

    with gr.Blocks(
        title="FlowPilot",
        theme=gr.themes.Soft(primary_hue="blue"),
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
                    workflow_visual = gr.Markdown(label="Workflow Preview")

                workflow_json = gr.Code(label="Workflow JSON", language="json")
                status_msg = gr.Textbox(label="Status", interactive=False)

                create_btn.click(
                    fn=create_workflow,
                    inputs=description_input,
                    outputs=[workflow_json, workflow_visual, status_msg],
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
                exec_json = gr.Code(
                    label="Workflow JSON (paste or load from Create tab)",
                    language="json",
                )
                exec_btn = gr.Button("Execute", variant="primary")
                exec_result = gr.Markdown()
                exec_btn.click(fn=execute_workflow, inputs=exec_json, outputs=exec_result)

            # ── Validate Tab ──
            with gr.Tab("Validate"):
                val_json = gr.Code(label="Workflow JSON", language="json")
                val_btn = gr.Button("Validate", variant="primary")
                val_result = gr.Markdown()
                val_btn.click(fn=validate_workflow, inputs=val_json, outputs=val_result)

            # ── Templates Tab ──
            with gr.Tab("Templates"):
                templates_list = gr.Markdown(value=get_templates_list())
                if template_names:
                    template_select = gr.Dropdown(
                        choices=template_names,
                        label="Load Template",
                    )
                    load_btn = gr.Button("Load", size="sm")
                    template_preview = gr.Markdown()
                    template_json = gr.Code(label="Template JSON", language="json")
                    load_btn.click(
                        fn=load_template,
                        inputs=template_select,
                        outputs=[template_json, template_preview],
                    )

            # ── History Tab ──
            with gr.Tab("History"):
                refresh_btn = gr.Button("Refresh", size="sm")
                history_md = gr.Markdown()
                stats_md = gr.Markdown()
                refresh_btn.click(fn=get_history_table, outputs=history_md)
                refresh_btn.click(fn=get_history_stats, outputs=stats_md)

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

Set environment variables to enable real API calls. Without credentials, connectors run in simulation mode.
""")

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860)
