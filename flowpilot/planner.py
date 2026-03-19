"""AI Planner — converts natural language descriptions into workflow graphs.

Uses Claude to decompose a plain English workflow description into
a structured DAG of nodes with connectors, actions, and dependencies.
"""

from __future__ import annotations

import json
import os
from typing import Any

from flowpilot.engine import WorkflowGraph, WorkflowNode


PLANNER_SYSTEM_PROMPT = """You are FlowPilot's workflow planner. You convert natural language
workflow descriptions into structured JSON workflow graphs.

Output ONLY valid JSON matching this schema:

{
  "name": "short workflow name",
  "description": "one-line description",
  "trigger": {
    "type": "cron|webhook|manual|event",
    "config": {}
  },
  "nodes": [
    {
      "id": "step_1",
      "name": "Human-readable step name",
      "connector": "connector_name",
      "action": "action_name",
      "config": {},
      "depends_on": []
    }
  ]
}

Available connectors and actions:
- slack: send_message, read_channel, create_channel
- github: create_issue, get_issues, create_comment, get_pull_requests, merge_pr
- email: send_email, read_inbox
- http: get, post, put, delete
- transform: filter, map, format_template, extract_field, join
- ai: summarise, classify, extract, generate
- file: read, write, append
- database: query, insert, update
- schedule: delay, wait_until
- notification: send_notification

Rules:
- Use descriptive node IDs (step_1, step_2, etc.)
- Set depends_on to reference upstream node IDs
- Parallelise independent steps
- Include transform nodes for data shaping between steps
- Set trigger type based on the description (cron for scheduled, webhook for event-driven, manual for on-demand)
- For cron triggers, include a "schedule" field in config (e.g., "0 9 * * *" for 9am daily)
- Output ONLY the JSON. No explanation. No markdown fences."""


class WorkflowPlanner:
    """Converts natural language to workflow graphs via Claude."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def plan(self, description: str) -> WorkflowGraph:
        """Generate a workflow graph from a natural language description.

        If the Anthropic SDK is available and ANTHROPIC_API_KEY is set,
        uses Claude to generate the workflow. Otherwise falls back to
        rule-based planning.
        """
        try:
            from anthropic import Anthropic
            if os.environ.get("ANTHROPIC_API_KEY"):
                return self._plan_with_claude(description)
        except ImportError:
            pass

        return self._plan_with_rules(description)

    def _plan_with_claude(self, description: str) -> WorkflowGraph:
        """Use Claude to generate the workflow graph."""
        from anthropic import Anthropic

        client = Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Create a workflow for: {description}",
            }],
        )

        text = response.content[0].text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        return WorkflowGraph.from_dict(data)

    def _plan_with_rules(self, description: str) -> WorkflowGraph:
        """Rule-based fallback planner for when Claude is not available."""
        desc_lower = description.lower()

        graph = WorkflowGraph(
            name=_extract_name(description),
            description=description,
        )

        # Detect trigger
        if any(w in desc_lower for w in ["every morning", "daily", "every day", "9am", "schedule"]):
            graph.trigger = {"type": "cron", "config": {"schedule": "0 9 * * *"}}
        elif any(w in desc_lower for w in ["when", "new issue", "new pr", "webhook"]):
            graph.trigger = {"type": "webhook", "config": {}}
        else:
            graph.trigger = {"type": "manual", "config": {}}

        nodes = []
        step = 1

        # Detect data sources
        if "github" in desc_lower and any(w in desc_lower for w in ["issue", "pr", "pull request"]):
            action = "get_pull_requests" if "pr" in desc_lower or "pull request" in desc_lower else "get_issues"
            nodes.append(WorkflowNode(
                id=f"step_{step}", name=f"Fetch from GitHub",
                connector="github", action=action,
                config={"repo": "owner/repo"},
            ))
            step += 1

        if "hacker news" in desc_lower or "hn" in desc_lower:
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Fetch Hacker News stories",
                connector="http", action="get",
                config={"url": "https://hacker-news.firebaseio.com/v0/topstories.json", "limit": 5},
            ))
            step += 1

        if "email" in desc_lower and "read" in desc_lower:
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Read emails",
                connector="email", action="read_inbox",
                config={"limit": 10},
            ))
            step += 1

        # Detect AI processing
        if any(w in desc_lower for w in ["summar", "classify", "extract", "analys"]):
            action = "summarise"
            if "classif" in desc_lower:
                action = "classify"
            elif "extract" in desc_lower:
                action = "extract"

            depends = [nodes[-1].id] if nodes else []
            nodes.append(WorkflowNode(
                id=f"step_{step}", name=f"AI {action}",
                connector="ai", action=action,
                config={"prompt": f"{action} the input data"},
                depends_on=depends,
            ))
            step += 1

        # Detect formatting/transform
        if any(w in desc_lower for w in ["format", "template", "combine"]):
            depends = [nodes[-1].id] if nodes else []
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Format output",
                connector="transform", action="format_template",
                config={"template": "{{result}}"},
                depends_on=depends,
            ))
            step += 1

        # Detect destinations
        if "slack" in desc_lower:
            channel = "#general"
            for word in desc_lower.split():
                if word.startswith("#"):
                    channel = word
                    break
            depends = [nodes[-1].id] if nodes else []
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Send to Slack",
                connector="slack", action="send_message",
                config={"channel": channel},
                depends_on=depends,
            ))
            step += 1

        if "email" in desc_lower and "send" in desc_lower:
            depends = [nodes[-1].id] if nodes else []
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Send email",
                connector="email", action="send_email",
                config={"to": "recipient@example.com", "subject": "FlowPilot notification"},
                depends_on=depends,
            ))
            step += 1

        if "notion" in desc_lower:
            depends = [nodes[-1].id] if nodes else []
            nodes.append(WorkflowNode(
                id=f"step_{step}", name="Add to Notion",
                connector="http", action="post",
                config={"url": "https://api.notion.com/v1/pages"},
                depends_on=depends,
            ))
            step += 1

        # Fallback: if no nodes detected, create a generic workflow
        if not nodes:
            nodes.append(WorkflowNode(
                id="step_1", name="Process input",
                connector="transform", action="format_template",
                config={"template": "{{input}}"},
            ))
            nodes.append(WorkflowNode(
                id="step_2", name="AI processing",
                connector="ai", action="summarise",
                config={"prompt": description},
                depends_on=["step_1"],
            ))

        for node in nodes:
            graph.add_node(node)

        return graph


def _extract_name(description: str) -> str:
    """Extract a short workflow name from the description."""
    words = description.split()[:6]
    name = " ".join(words)
    if len(description.split()) > 6:
        name += "..."
    return name
