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
- **Multi-Model Planner** — Support for Claude, OpenAI, Gemini, and Ollama with automatic fallback chain
- **Async Execution Engine** — Parallel node execution, retry logic, dependency resolution
- **14 Built-in Connectors** — Slack, GitHub, Email, HTTP, Transform, AI, Notification, Database, Google Workspace, Jira, AWS, Stripe, Twilio, PostgreSQL
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
- **Webhook Signature Verification** — HMAC verification for GitHub, Slack, Stripe, and generic webhooks
- **Cron Scheduler** — Schedule workflows on recurring intervals
- **Dry Run Mode** — Simulate execution without making real API calls
- **Live Execution Streaming** — Real-time node status updates during execution
- **Visual Graph Renderer** — Mermaid.js DAG diagrams with status colour coding
- **Docker Support** — Dockerfile and docker-compose.yml for one-command deployment
- **Environment Configuration** — Dev/staging/production profiles with env var overrides

### Security
- **Authentication & RBAC** — User management with Admin/Editor/Viewer roles and API key support
- **OAuth2 Integration** — OAuth2 authorization flows for Google, GitHub, Slack, Microsoft, Stripe
- **Secrets Vault** — Encrypted credential storage (Fernet) replacing raw environment variables

### Operations
- **Workflow Validator** — Catches cycles, missing deps, invalid connectors, broken conditions, and loop issues
- **Execution History** — SQLite-backed audit log with aggregate statistics
- **Workflow Versioning** — Track changes, diff between versions, rollback
- **Workflow Testing Framework** — Unit test nodes and full workflows with mocked responses
- **Execution Replay** — Re-run failed workflows from the point of failure
- **SLA Tracking** — Error budget monitoring with breach alerts per workflow
- **Rate Limiter** — Per-connector sliding window rate limiting
- **Multi-Channel Notifications** — Workflow event alerts via Slack, email, webhook, or desktop
- **Reporting** — Execution summaries, connector usage, SLA compliance reports with Markdown/JSON/CSV export and delivery via Slack, email, or file
- **Workflow Marketplace** — Discover, publish, rate, review, and install community templates
- **Import/Export** — Workflows in JSON, YAML, and TOML formats with zip bundling
- **Real-Time Monitoring** — WebSocket-based live execution monitoring with dashboard aggregation
- **Distributed Execution** — Redis-backed task queue with multi-worker scaling
- **Embeddable Widget** — HTML widget for triggering workflows from external apps

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
│               FlowPilot Dashboard (Gradio)               │
│ Create │ Execute │ Validate │ Templates │ History │ Reports│
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
| **google_workspace** | list_files, create_spreadsheet, append_rows, send_email, list_events, create_event | GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_API_KEY |
| **jira** | get_issues, create_issue, update_issue, add_comment, transition_issue, get_boards | JIRA_URL + JIRA_EMAIL + JIRA_API_TOKEN |
| **aws** | s3_list, s3_upload, s3_download, lambda_invoke, sqs_send, sqs_receive | AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY |
| **stripe** | list_payments, create_payment_link, get_customer, list_subscriptions, create_invoice | STRIPE_API_KEY |
| **twilio** | send_sms, make_call, send_whatsapp, get_messages | TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN |
| **postgres** | query, insert, update, delete, list_tables | POSTGRES_URL or POSTGRES_HOST/PORT/USER/PASSWORD |

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

# Reporting
flowpilot report summary                   # Execution summary (last 7 days)
flowpilot report connectors --days 30      # Connector usage report
flowpilot report sla                       # SLA compliance report
flowpilot report full --format json        # Full report as JSON
flowpilot report summary -o report.md      # Export to file
flowpilot report full --deliver slack --channel "#ops"  # Send to Slack

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

## Docker

```bash
# Quick start with Docker Compose
docker compose up

# Or build and run manually
docker build -t flowpilot .
docker run -p 7860:7860 -e ANTHROPIC_API_KEY=sk-ant-... flowpilot

# Override settings via environment
docker run -p 7860:7860 \
  -e FLOWPILOT_ENV=production \
  -e FLOWPILOT_AUTH_ENABLED=true \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v ./workflows:/app/workflows \
  flowpilot
```

## Project Structure

```
flowpilot/
├── __init__.py          # FlowPilot SDK entry point
├── __main__.py          # python -m flowpilot
├── engine.py            # Async engine (parallel, conditional, loop, join, approval, dry run, streaming)
├── planner.py           # NL → workflow graph (Claude + rules fallback)
├── multi_planner.py     # Multi-model planner (Claude, OpenAI, Gemini, Ollama)
├── validator.py         # Graph validation (cycles, deps, conditions, loops, joins, approvals)
├── auth.py              # Authentication and RBAC (Admin/Editor/Viewer roles, API keys)
├── oauth2.py            # OAuth2 authorization flows (Google, GitHub, Slack, Microsoft, Stripe)
├── env_config.py        # Environment configuration (dev/staging/production profiles)
├── scheduler.py         # Cron-based scheduling
├── history.py           # SQLite execution audit log
├── secrets.py           # Fernet-encrypted credential vault
├── versioning.py        # Workflow version control with diff and rollback
├── testing.py           # Workflow testing framework with mocks
├── replay.py            # Execution replay from point of failure
├── sla.py               # Error budget and SLA tracking
├── rate_limiter.py      # Per-connector sliding window rate limiter
├── notifications.py     # Multi-channel alerts (Slack, email, webhook, desktop)
├── monitoring.py        # Real-time WebSocket execution monitoring
├── distributed.py       # Distributed execution with Redis task queue
├── marketplace.py       # Workflow template marketplace
├── marketplace_v2.py    # Enhanced marketplace with reviews and recommendations
├── import_export.py     # Workflow import/export (JSON, YAML, TOML, zip bundles)
├── widget.py            # Embeddable HTML workflow trigger widget
├── webhook.py           # FastAPI webhook server with response mode
├── webhook_signing.py   # Webhook signature verification (GitHub, Slack, Stripe)
├── reporting.py         # Execution reports, connector usage, SLA compliance, export/delivery
├── cli.py               # CLI (create, run, validate, graph, secrets, sla, report, history, serve)
├── ui.py                # Gradio dashboard with Mermaid graphs, live streaming, and reports
└── connectors/
    ├── base.py              # BaseConnector ABC
    ├── slack.py             # Slack (webhook + Bot API)
    ├── github_connector.py  # GitHub REST API
    ├── email_connector.py   # SMTP send + IMAP read
    ├── http_connector.py    # Generic HTTP/REST
    ├── transform.py         # Data shaping (filter, map, format, extract)
    ├── ai_connector.py      # Claude AI processing
    ├── notification.py      # Desktop, SMS (Twilio), webhook notifications
    ├── database.py          # SQLite + PostgreSQL read/write
    ├── google_workspace.py  # Google Drive, Sheets, Gmail, Calendar
    ├── jira_connector.py    # Jira issues, boards, transitions
    ├── aws_connector.py     # AWS S3, Lambda, SQS
    ├── stripe_connector.py  # Stripe payments, subscriptions, invoices
    ├── twilio_connector.py  # Twilio SMS, voice, WhatsApp
    └── postgres_connector.py # PostgreSQL with connection pooling
Dockerfile               # Multi-stage Docker build
docker-compose.yml       # One-command deployment
templates/               # 10 pre-built workflow templates
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contact

- **Author:** Cobus Greyling
- **GitHub:** [@cobusgreyling](https://github.com/cobusgreyling)

---

<p align="center">Built with AI, for everyone who automates.</p>
