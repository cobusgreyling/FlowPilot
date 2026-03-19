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

### Core
- **Natural Language Planner** — Describe automations in plain English, get a structured workflow graph
- **Async Execution Engine** — Parallel node execution, retry logic, dependency resolution
- **8 Built-in Connectors** — Slack, GitHub, Email, HTTP, Transform, AI, Notification, Database
- **10 Workflow Templates** — Pre-built workflows ready to customise
- **Gradio Dashboard** — Visual UI with Mermaid graph rendering, live execution streaming, and monitoring
- **CLI** — Full command-line interface for scripting and automation
- **Plugin Architecture** — BaseConnector class for building custom integrations

### Advanced Node Types
- **Conditional Branching** — If/else nodes that route execution based on field evaluation
- **Loop/Iterator Nodes** — Process list items one-by-one with per-item execution
- **Join Nodes** — Merge results from parallel branches before continuing
- **Approval Gates** — Human-in-the-loop nodes that pause execution until approved

### Infrastructure
- **Webhook Server** — Receive events from external services with response mode support
- **Cron Scheduler** — Schedule workflows on recurring intervals
- **Dry Run Mode** — Simulate execution without making real API calls
- **Live Execution Streaming** — Real-time node status updates during execution
- **Visual Graph Renderer** — Mermaid.js DAG diagrams with status colour coding

### Operations
- **Workflow Validator** — Catches cycles, missing deps, invalid connectors, broken conditions, and loop issues
- **Execution History** — SQLite-backed audit log with aggregate statistics
- **Secrets Vault** — Encrypted credential storage (Fernet) replacing raw environment variables
- **Workflow Versioning** — Track changes, diff between versions, rollback
- **SLA Tracking** — Error budget monitoring with breach alerts per workflow
- **Rate Limiter** — Per-connector sliding window rate limiting
- **Workflow Marketplace** — Discover, publish, rate, and install community templates

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
| **notification** | send_notification (desktop, sms, webhook) | TWILIO_* for SMS |
| **database** | query, insert, update | DATABASE_URL |

Without credentials, connectors run in **simulation mode** — the workflow executes but API calls return mock responses.

## Node Types

| Type | Description | Use Case |
|------|-------------|----------|
| **standard** | Normal connector execution | API calls, data processing |
| **condition** | If/else branching | Route based on sentiment, priority, status |
| **loop** | Iterate over a list | Process each issue, email, or record |
| **join** | Merge parallel branches | Combine results before next step |
| **approval** | Human-in-the-loop gate | Require sign-off before deployment |

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
# Workflow management
flowpilot create "description"          # Create workflow from natural language
flowpilot create "desc" -o out.json     # Save to file
flowpilot create "desc" --save name     # Save to workflows/name.json
flowpilot run workflow.json             # Execute a workflow
flowpilot run workflow.json --dry-run   # Simulate without real API calls
flowpilot validate workflow.json        # Validate without executing
flowpilot graph workflow.json           # Generate Mermaid diagram
flowpilot list                          # List saved workflows and templates

# Operations
flowpilot history                       # Show execution history
flowpilot history --stats               # Show aggregate statistics
flowpilot sla                           # View SLA status and error budgets
flowpilot sla --set WF_ID "Name" 99.5  # Set SLA target

# Secrets
flowpilot secrets set SLACK_TOKEN xoxb-...  # Store encrypted credential
flowpilot secrets get SLACK_TOKEN           # Retrieve credential
flowpilot secrets list                      # List stored keys
flowpilot secrets delete SLACK_TOKEN        # Remove credential

# Dashboard
flowpilot serve                         # Launch Gradio dashboard
flowpilot serve --port 8080             # Custom port
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
├── __init__.py          # FlowPilot SDK entry point (v0.2.0)
├── __main__.py          # python -m flowpilot
├── engine.py            # Async engine (parallel, conditional, loop, join, approval, dry run, streaming)
├── planner.py           # NL → workflow graph (Claude + rules fallback)
├── validator.py         # Graph validation (cycles, deps, conditions, loops, joins, approvals)
├── scheduler.py         # Cron-based scheduling
├── history.py           # SQLite execution audit log
├── secrets.py           # Fernet-encrypted credential vault
├── versioning.py        # Workflow version control with diff and rollback
├── sla.py               # Error budget and SLA tracking
├── rate_limiter.py      # Per-connector sliding window rate limiter
├── marketplace.py       # Workflow template marketplace
├── webhook.py           # FastAPI webhook server with response mode
├── cli.py               # CLI (create, run, validate, graph, secrets, sla, history, serve)
├── ui.py                # Gradio dashboard with Mermaid graphs and live streaming
└── connectors/
    ├── base.py              # BaseConnector ABC
    ├── slack.py             # Slack (webhook + Bot API)
    ├── github_connector.py  # GitHub REST API
    ├── email_connector.py   # SMTP send + IMAP read
    ├── http_connector.py    # Generic HTTP/REST
    ├── transform.py         # Data shaping (filter, map, format, extract)
    ├── ai_connector.py      # Claude AI processing
    ├── notification.py      # Desktop, SMS (Twilio), webhook notifications
    └── database.py          # SQLite + PostgreSQL read/write
templates/               # 10 pre-built workflow templates
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contact

- **Author:** Cobus Greyling
- **GitHub:** [@cobusgreyling](https://github.com/cobusgreyling)

---

<p align="center">Built with AI, for everyone who automates.</p>
