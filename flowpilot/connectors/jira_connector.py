"""Jira connector — issues, boards, transitions."""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class JiraConnector(BaseConnector):
    """Interact with Jira for issue tracking and project management."""

    @property
    def name(self) -> str:
        return "jira"

    def _get_auth(self) -> tuple[str, str, str]:
        url = os.environ.get("JIRA_URL", "")
        email = os.environ.get("JIRA_EMAIL", "")
        token = os.environ.get("JIRA_API_TOKEN", "")
        return url, email, token

    def _api(self, method: str, path: str, json_data: dict = None) -> dict:
        url, email, token = self._get_auth()
        if not all([url, email, token]):
            return None
        if not HAS_REQUESTS:
            return None
        resp = _requests.request(
            method, f"{url.rstrip('/')}/rest/api/3/{path}",
            auth=(email, token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=json_data, timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def get_issues(self, config: dict, context: dict) -> dict:
        project = config.get("project", "")
        status = config.get("status", "")
        limit = config.get("limit", 20)
        jql = config.get("jql", "")
        if not jql:
            parts = []
            if project:
                parts.append(f"project = {project}")
            if status:
                parts.append(f"status = '{status}'")
            jql = " AND ".join(parts) if parts else "ORDER BY created DESC"
        result = self._api("GET", f"search?jql={jql}&maxResults={limit}")
        if result is None:
            return {"status": "simulated", "issues": [
                {"key": "PROJ-101", "summary": "Fix login bug", "status": "In Progress", "assignee": "alice"},
                {"key": "PROJ-102", "summary": "Add dark mode", "status": "To Do", "assignee": "bob"},
            ], "total": 2}
        issues = [
            {"key": i["key"], "summary": i["fields"]["summary"],
             "status": i["fields"]["status"]["name"],
             "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned")}
            for i in result.get("issues", [])
        ]
        return {"status": "success", "issues": issues, "total": result.get("total", 0)}

    def create_issue(self, config: dict, context: dict) -> dict:
        project = config.get("project", "")
        summary = config.get("summary", context.get("title", ""))
        issue_type = config.get("issue_type", "Task")
        description = config.get("description", context.get("description", ""))
        result = self._api("POST", "issue", {
            "fields": {
                "project": {"key": project},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]}
                ]} if description else None,
            }
        })
        if result is None:
            return {"status": "simulated", "key": f"{project}-999", "summary": summary}
        return {"status": "success", "key": result.get("key", ""), "id": result.get("id", "")}

    def update_issue(self, config: dict, context: dict) -> dict:
        issue_key = config.get("issue_key", "")
        fields = config.get("fields", {})
        result = self._api("PUT", f"issue/{issue_key}", {"fields": fields})
        if result is None:
            return {"status": "simulated", "issue_key": issue_key, "updated_fields": list(fields.keys())}
        return {"status": "success", "issue_key": issue_key}

    def add_comment(self, config: dict, context: dict) -> dict:
        issue_key = config.get("issue_key", "")
        body = config.get("body", context.get("comment", ""))
        result = self._api("POST", f"issue/{issue_key}/comment", {
            "body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": body}]}
            ]}
        })
        if result is None:
            return {"status": "simulated", "issue_key": issue_key, "comment": body[:100]}
        return {"status": "success", "issue_key": issue_key, "comment_id": result.get("id", "")}

    def transition_issue(self, config: dict, context: dict) -> dict:
        issue_key = config.get("issue_key", "")
        transition_name = config.get("transition", "")
        # First get available transitions
        result = self._api("GET", f"issue/{issue_key}/transitions")
        if result is None:
            return {"status": "simulated", "issue_key": issue_key, "transition": transition_name}
        transition_id = None
        for t in result.get("transitions", []):
            if t["name"].lower() == transition_name.lower():
                transition_id = t["id"]
                break
        if not transition_id:
            return {"status": "error", "error": f"Transition '{transition_name}' not found"}
        self._api("POST", f"issue/{issue_key}/transitions", {"transition": {"id": transition_id}})
        return {"status": "success", "issue_key": issue_key, "transition": transition_name}

    def get_boards(self, config: dict, context: dict) -> dict:
        url, email, token = self._get_auth()
        if not all([url, email, token]) or not HAS_REQUESTS:
            return {"status": "simulated", "boards": [
                {"id": 1, "name": "Engineering Board", "type": "scrum"},
                {"id": 2, "name": "Support Board", "type": "kanban"},
            ]}
        resp = _requests.get(
            f"{url.rstrip('/')}/rest/agile/1.0/board",
            auth=(email, token), timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "boards": [
            {"id": b["id"], "name": b["name"], "type": b.get("type", "")}
            for b in data.get("values", [])
        ]}

    def validate_config(self, action: str, config: dict) -> list[str]:
        errors = []
        if action == "create_issue" and not config.get("project"):
            errors.append("'project' key required")
        if action in ("update_issue", "add_comment", "transition_issue") and not config.get("issue_key"):
            errors.append("'issue_key' required")
        if action == "transition_issue" and not config.get("transition"):
            errors.append("'transition' name required")
        return errors
