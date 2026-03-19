<p align="center">
  <img src="logo.jpg" alt="FlowPilot Logo" width="600"/>
</p>

<h1 align="center">FlowPilot</h1>
<p align="center"><strong>AI-Powered Workflow Automation</strong></p>
<p align="center">Describe your workflows in plain English. FlowPilot wires up the APIs, triggers, and actions automatically.</p>

---

## What is FlowPilot?

FlowPilot is an open-source, self-hostable workflow automation platform that combines natural language with API orchestration. Describe what you want to automate in plain English — FlowPilot decomposes it into an executable workflow graph and runs it.

**Zapier meets AI** — but open-source, privacy-first, and running on your infrastructure.

## Features

- **Natural Language Planner** — Describe automations in plain English, get a structured workflow graph
- **Async Execution Engine** — Parallel node execution, retry logic, dependency resolution
- **6 Built-in Connectors** — Slack, GitHub, Email, HTTP, Transform, AI (Claude)
- **10 Workflow Templates** — Pre-built workflows ready to customise
- **Gradio Dashboard** — Visual UI for creating, executing, and monitoring workflows
- **CLI** — Full command-line interface for scripting and automation
- **Webhook Server** — Receive events from external services and trigger workflows
- **Cron Scheduler** — Schedule workflows on recurring intervals
- **Workflow Validator** — Catch structural issues before execution (cycles, missing deps, invalid connectors)
- **Execution History** — SQLite-backed audit log with aggregate statistics
- **Plugin Architecture** — BaseConnector class for building custom integrations

## Quick Start

```bash
git clone https://github.com/cobusgreyling/FlowPilot.git
cd FlowPilot
pip install -e ".[all]"
export ANTHROPIC_API_KEY=sk-ant-...
```

### Create a workflow from natural language

```bash
flowpilot create "When a new GitHub issue is created, summarise it with AI and post to Slack #dev"
```

### Run a template

```bash
flowpilot run templates/github_to_slack.json
```

### Launch the dashboard

```bash
flowpilot serve
# Open http://localhost:7860
```

### Python SDK

```python
from flowpilot import FlowPilot

fp = FlowPilot()
flow = fp.create(
    "Every morning at 9am, fetch top Hacker News stories and send to Slack #news"
)
result = fp.run(flow)
print(result)
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│               FlowPilot Dashboard (Gradio)          │
│   Create │ Execute │ Validate │ Templates │ History │
├─────────────────────────────────────────────────────┤
│                  CLI (flowpilot)                     │
│   create │ run │ validate │ list │ history │ serve   │
├─────────────────────────────────────────────────────┤
│              AI Planner (Claude / Rules)             │
│       Natural Language → Workflow Graph (DAG)        │
├──────────┬──────────┬───────────────────────────────┤
│ Triggers │ Engine   │   Connectors                  │
│ ┌──────┐ │ ┌──────┐ │   ┌──────────────────────┐   │
│ │ Cron │ │ │Async │ │   │ Slack   GitHub  HTTP │   │
│ │Webhk │ │ │Retry │ │   │ Email   AI   Transform│   │
│ │Manual│ │ │ DAG  │ │   │ + BaseConnector API   │   │
│ └──────┘ │ └──────┘ │   └──────────────────────┘   │
├──────────┴──────────┴───────────────────────────────┤
│  Validator │ Scheduler │ History (SQLite) │ Webhook  │
└─────────────────────────────────────────────────────┘
```

## Connectors

| Connector | Actions | Auth |
|-----------|---------|------|
| **slack** | send_message, read_channel, create_channel | SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL |
| **github** | get_issues, get_pull_requests, create_issue, create_comment, merge_pr | GITHUB_TOKEN |
| **email** | send_email, read_inbox | EMAIL_USERNAME + EMAIL_PASSWORD + SMTP_HOST |
| **http** | get, post, put, delete | Per-request headers |
| **transform** | filter, map, format_template, extract_field, join | None |
| **ai** | summarise, classify, extract, generate | ANTHROPIC_API_KEY |

Without credentials, connectors run in **simulation mode** — the workflow executes but API calls return mock responses.

## Templates

10 pre-built workflow templates in `templates/`:

| Template | Trigger | Description |
|----------|---------|-------------|
| github_to_slack | webhook | GitHub issues → AI summary → Slack |
| daily_news_digest | cron (9am) | Hacker News top stories → Slack |
| pr_review_notifier | webhook | New PRs → AI review → GitHub comment + Slack |
| email_to_slack | cron (15min) | Inbox → priority classify → Slack |
| data_pipeline | cron (6hr) | API fetch → transform → filter → AI analysis |
| incident_response | webhook | Alert → severity classify → GitHub issue + Slack + email |
| content_moderation | webhook | Content → AI classify → moderation team |
| customer_feedback | cron (8am) | Feedback API → sentiment + extraction → Slack |
| weekly_report | cron (Mon 9am) | GitHub activity → AI summary → Slack + email |
| multi_channel_broadcast | manual | Message → Slack + email + webhook (parallel) |

## CLI Reference

```bash
flowpilot create "description"     # Create workflow from natural language
flowpilot create "desc" -o out.json  # Save to file
flowpilot create "desc" --save name  # Save to workflows/name.json
flowpilot run workflow.json        # Execute a workflow
flowpilot validate workflow.json   # Validate without executing
flowpilot list                     # List saved workflows and templates
flowpilot history                  # Show execution history
flowpilot history --stats          # Show aggregate statistics
flowpilot serve                    # Launch Gradio dashboard
flowpilot serve --port 8080        # Custom port
```

## Building Custom Connectors

```python
from flowpilot.connectors.base import BaseConnector

class MyConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "my_service"

    def send(self, config: dict, context: dict) -> dict:
        # Your integration logic here
        return {"status": "success", "data": result}

# Register with the engine
engine.register_connector("my_service", MyConnector())
```

## Project Structure

```
flowpilot/
├── __init__.py          # FlowPilot SDK entry point
├── __main__.py          # python -m flowpilot
├── engine.py            # Async workflow execution engine
├── planner.py           # NL → workflow graph (Claude + rules fallback)
├── validator.py         # Graph validation (cycles, deps, connectors)
├── scheduler.py         # Cron-based scheduling
├── history.py           # SQLite execution audit log
├── webhook.py           # FastAPI webhook trigger server
├── cli.py               # Command-line interface
├── ui.py                # Gradio dashboard
└── connectors/
    ├── base.py              # BaseConnector ABC
    ├── slack.py             # Slack (webhook + Bot API)
    ├── github_connector.py  # GitHub REST API
    ├── email_connector.py   # SMTP send + IMAP read
    ├── http_connector.py    # Generic HTTP/REST
    ├── transform.py         # Data shaping (filter, map, format, extract)
    └── ai_connector.py      # Claude AI processing
templates/               # 10 pre-built workflow templates
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contact

- **Author:** Cobus Greyling
- **GitHub:** [@cobusgreyling](https://github.com/cobusgreyling)

---

<p align="center">Built with AI, for everyone who automates.</p>
