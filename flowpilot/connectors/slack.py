"""Slack connector — send messages and read channels."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen

from flowpilot.connectors.base import BaseConnector


class SlackConnector(BaseConnector):
    """Slack integration via webhook or Bot API."""

    def __init__(self, token: str | None = None, webhook_url: str | None = None):
        self._token = token or os.environ.get("SLACK_BOT_TOKEN")
        self._webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")

    @property
    def name(self) -> str:
        return "slack"

    def send_message(self, config: dict, context: dict) -> dict:
        """Send a message to a Slack channel.

        Config:
            channel: Channel name or ID (e.g., "#general")
            text: Message text (optional — uses context data if not set)
        """
        channel = config.get("channel", "#general")
        text = config.get("text") or _format_context(context)

        if self._webhook_url:
            return self._send_via_webhook(text)

        if self._token:
            return self._send_via_api(channel, text)

        return {
            "status": "simulated",
            "channel": channel,
            "text": text,
            "message": "No SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL configured — message simulated",
        }

    def read_channel(self, config: dict, context: dict) -> dict:
        """Read recent messages from a Slack channel.

        Config:
            channel: Channel ID
            limit: Number of messages (default 10)
        """
        channel = config.get("channel")
        limit = config.get("limit", 10)

        if not self._token:
            return {
                "status": "simulated",
                "channel": channel,
                "messages": [],
                "message": "No SLACK_BOT_TOKEN configured — read simulated",
            }

        data = self._api_call("conversations.history", {
            "channel": channel,
            "limit": str(limit),
        })
        return {
            "status": "success",
            "channel": channel,
            "messages": data.get("messages", []),
        }

    def _send_via_webhook(self, text: str) -> dict:
        payload = json.dumps({"text": text}).encode()
        req = Request(self._webhook_url, data=payload, headers={"Content-Type": "application/json"})
        urlopen(req)
        return {"status": "success", "method": "webhook", "text": text}

    def _send_via_api(self, channel: str, text: str) -> dict:
        return self._api_call("chat.postMessage", {
            "channel": channel,
            "text": text,
        })

    def _api_call(self, method: str, params: dict) -> dict:
        url = f"https://slack.com/api/{method}"
        payload = json.dumps(params).encode()
        req = Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        })
        with urlopen(req) as resp:
            return json.loads(resp.read())


def _format_context(context: dict) -> str:
    """Format context dict into a readable Slack message."""
    parts = []
    for key, value in context.items():
        if isinstance(value, dict):
            msg = value.get("message") or value.get("text") or value.get("result") or str(value)
            parts.append(f"*{key}*: {msg}")
        else:
            parts.append(f"*{key}*: {value}")
    return "\n".join(parts) if parts else "FlowPilot workflow completed"
