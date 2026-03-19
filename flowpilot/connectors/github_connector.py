"""GitHub connector — issues, PRs, and comments."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen


from flowpilot.connectors.base import BaseConnector


class GitHubConnector(BaseConnector):
    """GitHub integration via the REST API."""

    def __init__(self, token: str | None = None):
        self._token = token or os.environ.get("GITHUB_TOKEN")

    @property
    def name(self) -> str:
        return "github"

    def get_issues(self, config: dict, context: dict) -> dict:
        """Fetch open issues from a repository.

        Config:
            repo: "owner/repo"
            state: "open" | "closed" | "all" (default "open")
            limit: Number of issues (default 10)
        """
        repo = config.get("repo", "")
        state = config.get("state", "open")
        limit = config.get("limit", 10)

        if not self._token:
            return {
                "status": "simulated",
                "repo": repo,
                "issues": [],
                "message": "No GITHUB_TOKEN configured — simulated",
            }

        data = self._api(f"repos/{repo}/issues?state={state}&per_page={limit}")
        issues = [
            {"number": i["number"], "title": i["title"], "state": i["state"], "url": i["html_url"]}
            for i in data
        ]
        return {"status": "success", "repo": repo, "issues": issues}

    def get_pull_requests(self, config: dict, context: dict) -> dict:
        """Fetch pull requests from a repository.

        Config:
            repo: "owner/repo"
            state: "open" | "closed" | "all" (default "open")
        """
        repo = config.get("repo", "")
        state = config.get("state", "open")

        if not self._token:
            return {"status": "simulated", "repo": repo, "pull_requests": []}

        data = self._api(f"repos/{repo}/pulls?state={state}")
        prs = [
            {"number": p["number"], "title": p["title"], "state": p["state"], "url": p["html_url"]}
            for p in data
        ]
        return {"status": "success", "repo": repo, "pull_requests": prs}

    def create_issue(self, config: dict, context: dict) -> dict:
        """Create a new issue.

        Config:
            repo: "owner/repo"
            title: Issue title
            body: Issue body (optional — uses context data if not set)
        """
        repo = config.get("repo", "")
        title = config.get("title", "FlowPilot automated issue")
        body = config.get("body") or _context_to_body(context)

        if not self._token:
            return {"status": "simulated", "repo": repo, "title": title}

        data = self._api(
            f"repos/{repo}/issues",
            method="POST",
            body={"title": title, "body": body},
        )
        return {"status": "success", "issue_number": data["number"], "url": data["html_url"]}

    def create_comment(self, config: dict, context: dict) -> dict:
        """Add a comment to an issue or PR.

        Config:
            repo: "owner/repo"
            issue_number: Issue or PR number
            body: Comment text
        """
        repo = config.get("repo", "")
        number = config.get("issue_number", 1)
        body = config.get("body") or _context_to_body(context)

        if not self._token:
            return {"status": "simulated", "repo": repo, "issue_number": number}

        data = self._api(
            f"repos/{repo}/issues/{number}/comments",
            method="POST",
            body={"body": body},
        )
        return {"status": "success", "comment_id": data["id"], "url": data["html_url"]}

    def _api(self, endpoint: str, method: str = "GET", body: dict | None = None) -> Any:
        url = f"https://api.github.com/{endpoint}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {self._token}",
        }
        data = json.dumps(body).encode() if body else None
        req = Request(url, data=data, headers=headers, method=method)
        with urlopen(req) as resp:
            return json.loads(resp.read())


def _context_to_body(context: dict) -> str:
    parts = []
    for key, val in context.items():
        if isinstance(val, dict):
            parts.append(f"**{key}**: {val.get('message', str(val))}")
        else:
            parts.append(f"**{key}**: {val}")
    return "\n\n".join(parts) if parts else "Automated by FlowPilot"
