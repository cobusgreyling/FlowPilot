<p align="center">
  <img src="logo.jpg" alt="FlowPilot Logo" width="600"/>
</p>

<h1 align="center">FlowPilot</h1>
<p align="center"><strong>AI-Powered Workflow Automation</strong></p>
<p align="center">Describe your workflows in plain English. FlowPilot wires up the APIs, triggers, and actions automatically.</p>

---

## What is FlowPilot?

FlowPilot is an open-source, self-hostable workflow automation platform that combines the simplicity of no-code tools with the power of agentic AI. Instead of manually dragging and dropping connectors between services, you simply describe what you want to automate in natural language — and FlowPilot builds the workflow for you.

Think of it as **Zapier meets AI** — but open-source, privacy-first, and running entirely on your infrastructure.

### Key Features

- **Natural Language Workflows** — Describe automations in plain English (e.g., *"When a new issue is created in GitHub, post a summary to Slack and add it to my Notion board"*)
- **Visual Flow Editor** — Review, edit, and fine-tune AI-generated workflows in an intuitive drag-and-drop UI
- **100+ Integrations** — Connect to popular services like Slack, GitHub, Notion, Google Sheets, email, databases, and more
- **Self-Hostable** — Run on your own infrastructure with full control over your data
- **Extensible Plugin System** — Build custom connectors and actions with a simple plugin API
- **Event-Driven Architecture** — Trigger workflows from webhooks, schedules (cron), file changes, or API calls
- **AI Agent Orchestration** — Chain multiple AI agents together within a single workflow

## Getting Started

### Prerequisites

- Python 3.10+
- Docker (optional, for containerized deployment)

### Installation

```bash
# Clone the repository
git clone https://github.com/cobusgreyling/FlowPilot.git
cd FlowPilot

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python -m flowpilot serve
```

### Docker

```bash
docker pull cobusgreyling/flowpilot:latest
docker run -p 8080:8080 cobusgreyling/flowpilot:latest
```

Then open [http://localhost:8080](http://localhost:8080) in your browser.

### Quick Example

Create your first workflow via the CLI:

```bash
flowpilot create "Every morning at 9am, fetch the top 5 Hacker News stories and send them to my Slack channel #news"
```

Or use the Python SDK:

```python
from flowpilot import FlowPilot

fp = FlowPilot()
flow = fp.create(
    "When a new PR is opened in my repo, run the tests and post the result as a comment"
)
flow.activate()
```

## Architecture

```
┌─────────────────────────────────────────────┐
│                 FlowPilot UI                │
│           (Visual Flow Editor)              │
├─────────────────────────────────────────────┤
│              AI Planner Engine              │
│    (NL → workflow graph translation)        │
├──────────┬──────────┬───────────────────────┤
│ Triggers │ Actions  │   Integrations        │
│ (cron,   │ (API     │   (Slack, GitHub,     │
│  webhook,│  calls,  │    Notion, Gmail,     │
│  event)  │  scripts)│    Sheets, DBs...)    │
├──────────┴──────────┴───────────────────────┤
│            Execution Engine                 │
│     (async, retry, logging, monitoring)     │
└─────────────────────────────────────────────┘
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Contact

- **Author:** Cobus Greyling
- **GitHub:** [@cobusgreyling](https://github.com/cobusgreyling)

---

<p align="center">Built with AI, for everyone who automates.</p>
