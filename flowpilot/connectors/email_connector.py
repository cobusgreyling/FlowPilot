"""Email connector — send and read emails via SMTP/IMAP."""

from __future__ import annotations

import email
import imaplib
import os
import smtplib
from email.mime.text import MIMEText
from typing import Any

from flowpilot.connectors.base import BaseConnector


class EmailConnector(BaseConnector):
    """Email integration via SMTP (send) and IMAP (read)."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        imap_host: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self._smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self._smtp_port = smtp_port
        self._imap_host = imap_host or os.environ.get("IMAP_HOST", "imap.gmail.com")
        self._username = username or os.environ.get("EMAIL_USERNAME")
        self._password = password or os.environ.get("EMAIL_PASSWORD")

    @property
    def name(self) -> str:
        return "email"

    def send_email(self, config: dict, context: dict) -> dict:
        """Send an email.

        Config:
            to: Recipient email address
            subject: Email subject
            body: Email body (optional — uses context data if not set)
        """
        to = config.get("to", "")
        subject = config.get("subject", "FlowPilot Notification")
        body = config.get("body") or _context_to_text(context)

        if not self._username or not self._password:
            return {
                "status": "simulated",
                "to": to,
                "subject": subject,
                "message": "No EMAIL_USERNAME/EMAIL_PASSWORD configured — simulated",
            }

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self._username
        msg["To"] = to

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.starttls()
            server.login(self._username, self._password)
            server.send_message(msg)

        return {"status": "success", "to": to, "subject": subject}

    def read_inbox(self, config: dict, context: dict) -> dict:
        """Read recent emails from the inbox.

        Config:
            folder: IMAP folder (default "INBOX")
            limit: Number of emails to fetch (default 10)
            unseen_only: Only fetch unread emails (default True)
        """
        folder = config.get("folder", "INBOX")
        limit = config.get("limit", 10)
        unseen_only = config.get("unseen_only", True)

        if not self._username or not self._password:
            return {
                "status": "simulated",
                "folder": folder,
                "emails": [],
                "message": "No EMAIL_USERNAME/EMAIL_PASSWORD configured — simulated",
            }

        mail = imaplib.IMAP4_SSL(self._imap_host)
        mail.login(self._username, self._password)
        mail.select(folder)

        criteria = "UNSEEN" if unseen_only else "ALL"
        _, message_ids = mail.search(None, criteria)
        ids = message_ids[0].split()[-limit:]

        emails = []
        for mid in ids:
            _, data = mail.fetch(mid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)
            emails.append({
                "from": msg["From"],
                "subject": msg["Subject"],
                "date": msg["Date"],
                "body": _get_body(msg),
            })

        mail.logout()
        return {"status": "success", "folder": folder, "emails": emails}


def _context_to_text(context: dict) -> str:
    parts = []
    for key, val in context.items():
        if isinstance(val, dict):
            parts.append(f"{key}: {val.get('message', str(val))}")
        else:
            parts.append(f"{key}: {val}")
    return "\n".join(parts) if parts else "Automated notification from FlowPilot"


def _get_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
    return msg.get_payload(decode=True).decode(errors="replace")
