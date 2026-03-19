"""Notification connector — desktop, SMS (Twilio), and push notifications."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

from flowpilot.connectors.base import BaseConnector


class NotificationConnector(BaseConnector):
    """Multi-channel notification connector."""

    def __init__(self, twilio_sid: str | None = None, twilio_token: str | None = None, twilio_from: str | None = None):
        self._twilio_sid = twilio_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self._twilio_token = twilio_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self._twilio_from = twilio_from or os.environ.get("TWILIO_FROM_NUMBER")

    @property
    def name(self) -> str:
        return "notification"

    def send_notification(self, config: dict, context: dict) -> dict:
        """Send a notification via the configured channel.

        Config:
            channel: "desktop" | "sms" | "webhook" (default "desktop")
            message: Notification text (optional — uses context data)
            title: Notification title (default "FlowPilot")
            to: Phone number for SMS, URL for webhook
        """
        channel = config.get("channel", "desktop")
        message = config.get("message") or _format_context(context)
        title = config.get("title", "FlowPilot")

        if channel == "desktop":
            return self._desktop_notify(title, message)
        elif channel == "sms":
            return self._sms_notify(config.get("to", ""), message)
        elif channel == "webhook":
            return self._webhook_notify(config.get("to", ""), title, message)
        else:
            return {"status": "error", "message": f"Unknown notification channel: {channel}"}

    def _desktop_notify(self, title: str, message: str) -> dict:
        """Send a desktop notification using the OS notification system."""
        platform = sys.platform

        try:
            if platform == "darwin":
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ], check=True, capture_output=True)
            elif platform == "linux":
                subprocess.run(
                    ["notify-send", title, message],
                    check=True, capture_output=True,
                )
            elif platform == "win32":
                # PowerShell toast notification
                ps_cmd = (
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                    f"ContentType = WindowsRuntime] | Out-Null; "
                    f"$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                    f"GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                    f"$text = $template.GetElementsByTagName('text'); "
                    f"$text[0].AppendChild($template.CreateTextNode('{title}')); "
                    f"$text[1].AppendChild($template.CreateTextNode('{message}')); "
                )
                subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
            else:
                return {"status": "simulated", "message": f"Desktop notifications not supported on {platform}"}

            return {"status": "success", "channel": "desktop", "title": title, "message": message}
        except Exception as e:
            return {"status": "error", "channel": "desktop", "error": str(e)}

    def _sms_notify(self, to: str, message: str) -> dict:
        """Send an SMS via Twilio."""
        if not all([self._twilio_sid, self._twilio_token, self._twilio_from]):
            return {
                "status": "simulated",
                "channel": "sms",
                "to": to,
                "message": "No Twilio credentials configured — simulated",
            }

        import base64
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio_sid}/Messages.json"
        data = f"To={to}&From={self._twilio_from}&Body={message}".encode()
        auth = base64.b64encode(f"{self._twilio_sid}:{self._twilio_token}".encode()).decode()

        req = Request(url, data=data, headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        try:
            with urlopen(req) as resp:
                result = json.loads(resp.read())
                return {"status": "success", "channel": "sms", "sid": result.get("sid"), "to": to}
        except Exception as e:
            return {"status": "error", "channel": "sms", "error": str(e)}

    def _webhook_notify(self, url: str, title: str, message: str) -> dict:
        """Send a notification via webhook POST."""
        if not url:
            return {"status": "error", "message": "No webhook URL configured"}

        payload = json.dumps({"title": title, "message": message}).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})

        try:
            with urlopen(req) as resp:
                return {"status": "success", "channel": "webhook", "status_code": resp.status}
        except Exception as e:
            return {"status": "error", "channel": "webhook", "error": str(e)}


def _format_context(context: dict) -> str:
    parts = []
    for key, val in context.items():
        if isinstance(val, dict):
            parts.append(val.get("message") or val.get("text") or str(val))
        else:
            parts.append(str(val))
    return " | ".join(parts) if parts else "FlowPilot workflow completed"
