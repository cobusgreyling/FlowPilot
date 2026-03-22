"""Google Workspace connector — Drive, Sheets, Gmail, Calendar."""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)


class GoogleWorkspaceConnector(BaseConnector):
    """Interact with Google Drive, Sheets, Gmail, and Calendar."""

    @property
    def name(self) -> str:
        return "google_workspace"

    def _get_credentials(self):
        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        api_key = os.environ.get("GOOGLE_API_KEY")
        if sa_json or api_key:
            return True
        return False

    # --- Drive ---

    def list_files(self, config: dict, context: dict) -> dict:
        query = config.get("query", "")
        limit = config.get("limit", 10)
        folder_id = config.get("folder_id", "")
        if not self._get_credentials():
            logger.info("Google API not configured, returning simulated response")
            return {"status": "simulated", "files": [
                {"id": "file_1", "name": "Report Q1.docx", "mimeType": "application/vnd.google-apps.document"},
                {"id": "file_2", "name": "Budget.xlsx", "mimeType": "application/vnd.google-apps.spreadsheet"},
            ], "total": 2}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )
            service = build("drive", "v3", credentials=creds)
            q = f"'{folder_id}' in parents" if folder_id else None
            if query:
                q = f"{q} and name contains '{query}'" if q else f"name contains '{query}'"
            results = service.files().list(q=q, pageSize=limit, fields="files(id, name, mimeType, modifiedTime)").execute()
            return {"status": "success", "files": results.get("files", []), "total": len(results.get("files", []))}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # --- Sheets ---

    def create_spreadsheet(self, config: dict, context: dict) -> dict:
        title = config.get("title", "New Spreadsheet")
        if not self._get_credentials():
            return {"status": "simulated", "spreadsheet_id": "sim_sheet_123", "title": title, "url": "https://docs.google.com/spreadsheets/d/sim_sheet_123"}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            spreadsheet = service.spreadsheets().create(body={"properties": {"title": title}}).execute()
            return {"status": "success", "spreadsheet_id": spreadsheet["spreadsheetId"], "title": title, "url": spreadsheet.get("spreadsheetUrl", "")}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def append_rows(self, config: dict, context: dict) -> dict:
        spreadsheet_id = config.get("spreadsheet_id", "")
        sheet_range = config.get("range", "Sheet1!A1")
        rows = config.get("rows", context.get("rows", []))
        if not self._get_credentials() or not spreadsheet_id:
            return {"status": "simulated", "updated_rows": len(rows), "spreadsheet_id": spreadsheet_id}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", credentials=creds)
            result = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id, range=sheet_range,
                valueInputOption="USER_ENTERED", body={"values": rows},
            ).execute()
            return {"status": "success", "updated_rows": result.get("updates", {}).get("updatedRows", 0)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # --- Gmail ---

    def send_email(self, config: dict, context: dict) -> dict:
        to = config.get("to", "")
        subject = config.get("subject", "")
        body = config.get("body", context.get("message", ""))
        if not self._get_credentials():
            return {"status": "simulated", "to": to, "subject": subject, "message": "Email simulated"}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json, base64
            from email.mime.text import MIMEText
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/gmail.send"],
            )
            service = build("gmail", "v1", credentials=creds)
            msg = MIMEText(body)
            msg["to"] = to
            msg["subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return {"status": "success", "to": to, "subject": subject}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # --- Calendar ---

    def list_events(self, config: dict, context: dict) -> dict:
        calendar_id = config.get("calendar_id", "primary")
        limit = config.get("limit", 10)
        if not self._get_credentials():
            return {"status": "simulated", "events": [
                {"id": "evt_1", "summary": "Team Standup", "start": "2025-01-01T09:00:00Z"},
                {"id": "evt_2", "summary": "Sprint Review", "start": "2025-01-01T14:00:00Z"},
            ]}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/calendar.readonly"],
            )
            service = build("calendar", "v3", credentials=creds)
            events = service.events().list(calendarId=calendar_id, maxResults=limit).execute()
            return {"status": "success", "events": events.get("items", [])}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def create_event(self, config: dict, context: dict) -> dict:
        summary = config.get("summary", "New Event")
        start = config.get("start", "")
        end = config.get("end", "")
        calendar_id = config.get("calendar_id", "primary")
        if not self._get_credentials():
            return {"status": "simulated", "event_id": "sim_evt_123", "summary": summary}
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            service = build("calendar", "v3", credentials=creds)
            event = service.events().insert(calendarId=calendar_id, body={
                "summary": summary,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
            }).execute()
            return {"status": "success", "event_id": event["id"], "summary": summary}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def validate_config(self, action: str, config: dict) -> list[str]:
        errors = []
        if action == "send_email" and not config.get("to"):
            errors.append("'to' email address required")
        if action == "append_rows" and not config.get("spreadsheet_id"):
            errors.append("'spreadsheet_id' required")
        if action == "create_event" and not config.get("start"):
            errors.append("'start' datetime required")
        return errors
