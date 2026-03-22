"""Multi-channel notification system for workflow events."""

import json
import logging
import os
import platform
import smtplib
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from email.mime.text import MIMEText
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NotificationChannel(Enum):
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"
    DESKTOP = "desktop"


class NotificationEvent(Enum):
    WORKFLOW_SUCCESS = "workflow_success"
    WORKFLOW_FAILURE = "workflow_failure"
    WORKFLOW_TIMEOUT = "workflow_timeout"
    APPROVAL_REQUIRED = "approval_required"
    SLA_BREACH = "sla_breach"
    ERROR_BUDGET_WARNING = "error_budget_warning"


@dataclass
class NotificationRule:
    workflow_id: str  # "*" for all workflows
    events: list[str]
    channels: list[str]
    config: dict = field(default_factory=dict)
    rule_id: str = ""
    active: bool = True

    def __post_init__(self):
        if not self.rule_id:
            self.rule_id = uuid.uuid4().hex[:12]


class NotificationManager:
    """Manages notification rules and dispatches alerts."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_rules (
                    rule_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    events TEXT NOT NULL,
                    channels TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def add_rule(self, rule: NotificationRule) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO notification_rules (rule_id, workflow_id, events, channels, config) VALUES (?, ?, ?, ?, ?)",
                (rule.rule_id, rule.workflow_id, json.dumps(rule.events), json.dumps(rule.channels), json.dumps(rule.config)),
            )
            conn.commit()
        return rule.rule_id

    def remove_rule(self, rule_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM notification_rules WHERE rule_id = ?", (rule_id,))
            conn.commit()

    def list_rules(self) -> list[NotificationRule]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT rule_id, workflow_id, events, channels, config, active FROM notification_rules")
            return [
                NotificationRule(
                    rule_id=r[0], workflow_id=r[1], events=json.loads(r[2]),
                    channels=json.loads(r[3]), config=json.loads(r[4]), active=bool(r[5]),
                )
                for r in cursor.fetchall()
            ]

    def notify(self, event: NotificationEvent, workflow_id: str, details: dict):
        rules = self.list_rules()
        for rule in rules:
            if not rule.active:
                continue
            if rule.workflow_id != "*" and rule.workflow_id != workflow_id:
                continue
            if event.value not in rule.events:
                continue
            message = self._format_message(event, workflow_id, details)
            for channel in rule.channels:
                try:
                    if channel == NotificationChannel.SLACK.value:
                        self._send_slack(message, rule.config)
                    elif channel == NotificationChannel.EMAIL.value:
                        self._send_email(f"FlowPilot: {event.value}", message, rule.config)
                    elif channel == NotificationChannel.WEBHOOK.value:
                        self._send_webhook({"event": event.value, "workflow_id": workflow_id, "details": details}, rule.config)
                    elif channel == NotificationChannel.DESKTOP.value:
                        self._send_desktop("FlowPilot", message)
                except Exception as e:
                    logger.error(f"Failed to send {channel} notification: {e}")

    def _format_message(self, event: NotificationEvent, workflow_id: str, details: dict) -> str:
        status_icons = {
            NotificationEvent.WORKFLOW_SUCCESS: "✅", NotificationEvent.WORKFLOW_FAILURE: "❌",
            NotificationEvent.WORKFLOW_TIMEOUT: "⏱️", NotificationEvent.APPROVAL_REQUIRED: "👋",
            NotificationEvent.SLA_BREACH: "🚨", NotificationEvent.ERROR_BUDGET_WARNING: "⚠️",
        }
        icon = status_icons.get(event, "📋")
        msg = f"{icon} {event.value.replace('_', ' ').title()}\nWorkflow: {workflow_id}"
        if "error" in details:
            msg += f"\nError: {details['error']}"
        if "duration_ms" in details:
            msg += f"\nDuration: {details['duration_ms']}ms"
        return msg

    def _send_slack(self, message: str, config: dict):
        url = config.get("webhook_url", os.environ.get("SLACK_WEBHOOK_URL", ""))
        if not url:
            logger.warning("No Slack webhook URL configured")
            return
        if HAS_REQUESTS:
            requests.post(url, json={"text": message}, timeout=10)
        else:
            logger.warning("requests library not installed, cannot send Slack notification")

    def _send_email(self, subject: str, body: str, config: dict):
        smtp_host = config.get("smtp_host", os.environ.get("SMTP_HOST", "smtp.gmail.com"))
        smtp_port = int(config.get("smtp_port", os.environ.get("SMTP_PORT", "587")))
        username = config.get("username", os.environ.get("EMAIL_USERNAME", ""))
        password = config.get("password", os.environ.get("EMAIL_PASSWORD", ""))
        to_addr = config.get("to", "")
        if not all([username, password, to_addr]):
            logger.warning("Email notification not fully configured")
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = username
        msg["To"] = to_addr
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

    def _send_webhook(self, payload: dict, config: dict):
        url = config.get("url", "")
        if not url:
            logger.warning("No webhook URL configured")
            return
        if HAS_REQUESTS:
            headers = config.get("headers", {"Content-Type": "application/json"})
            requests.post(url, json=payload, headers=headers, timeout=10)

    def _send_desktop(self, title: str, message: str):
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'], check=True)
            elif system == "Linux":
                subprocess.run(["notify-send", title, message], check=True)
            elif system == "Windows":
                subprocess.run(["powershell", "-Command", f"[System.Windows.MessageBox]::Show('{message}', '{title}')"], check=True)
        except Exception as e:
            logger.warning(f"Desktop notification failed: {e}")

    def test_channel(self, channel: str, config: dict) -> bool:
        try:
            if channel == "slack":
                self._send_slack("🧪 FlowPilot test notification", config)
            elif channel == "email":
                self._send_email("FlowPilot Test", "This is a test notification.", config)
            elif channel == "webhook":
                self._send_webhook({"test": True, "message": "FlowPilot test"}, config)
            elif channel == "desktop":
                self._send_desktop("FlowPilot", "Test notification")
            return True
        except Exception as e:
            logger.error(f"Test notification failed for {channel}: {e}")
            return False
