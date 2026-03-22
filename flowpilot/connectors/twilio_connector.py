"""Twilio connector — SMS, voice calls, and WhatsApp messaging."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flowpilot.connectors.base import BaseConnector


class TwilioConnector(BaseConnector):
    """Twilio integration via REST API.

    Supports sending SMS, making voice calls, WhatsApp messaging,
    and retrieving message history.
    """

    API_BASE = "https://api.twilio.com/2010-04-01"

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
    ):
        self._account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self._auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self._from_number = from_number or os.environ.get("TWILIO_FROM_NUMBER")

    @property
    def name(self) -> str:
        return "twilio"

    @property
    def _has_credentials(self) -> bool:
        return bool(self._account_sid and self._auth_token)

    def validate_config(self, action: str, config: dict) -> list[str]:
        """Validate config for a specific action."""
        errors: list[str] = []
        if action == "send_sms":
            if not config.get("to"):
                errors.append("'to' (phone number) is required for send_sms")
            if not config.get("body"):
                errors.append("'body' (message text) is required for send_sms")
        elif action == "make_call":
            if not config.get("to"):
                errors.append("'to' (phone number) is required for make_call")
            if not config.get("twiml") and not config.get("url"):
                errors.append("'twiml' or 'url' is required for make_call")
        elif action == "send_whatsapp":
            if not config.get("to"):
                errors.append("'to' (phone number with country code) is required for send_whatsapp")
            if not config.get("body"):
                errors.append("'body' (message text) is required for send_whatsapp")
        elif action == "get_messages":
            pass  # no required fields
        else:
            errors.append(f"Unknown action: {action}")
        return errors

    def send_sms(self, config: dict, context: dict) -> dict:
        """Send an SMS message via Twilio.

        Config:
            to: Recipient phone number (E.164 format, e.g. "+15551234567")
            body: Message text
            from_number: Override default sender number (optional)
        """
        to = config.get("to", "")
        body = config.get("body", "")
        from_number = config.get("from_number", self._from_number or "")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "to": to,
                "from": from_number,
                "body": body,
                "sid": "SM_sim_abc123",
                "message": "No Twilio credentials configured — SMS sending simulated",
            }

        try:
            data = self._api("POST", f"/Accounts/{self._account_sid}/Messages.json", params={
                "To": to,
                "From": from_number,
                "Body": body,
            })
            return {
                "status": "success",
                "sid": data["sid"],
                "to": data["to"],
                "from": data["from"],
                "body": data["body"],
                "date_sent": data.get("date_sent"),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def make_call(self, config: dict, context: dict) -> dict:
        """Initiate a voice call via Twilio.

        Config:
            to: Recipient phone number (E.164 format)
            twiml: TwiML instructions for the call (e.g. "<Response><Say>Hello</Say></Response>")
            url: URL returning TwiML (alternative to twiml)
            from_number: Override default caller ID (optional)
        """
        to = config.get("to", "")
        twiml = config.get("twiml", "")
        url = config.get("url", "")
        from_number = config.get("from_number", self._from_number or "")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "to": to,
                "from": from_number,
                "call_sid": "CA_sim_abc123",
                "message": "No Twilio credentials configured — call simulated",
            }

        try:
            params: dict[str, str] = {"To": to, "From": from_number}
            if twiml:
                params["Twiml"] = twiml
            elif url:
                params["Url"] = url

            data = self._api("POST", f"/Accounts/{self._account_sid}/Calls.json", params=params)
            return {
                "status": "success",
                "call_sid": data["sid"],
                "to": data["to"],
                "from": data["from"],
                "call_status": data.get("status"),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def send_whatsapp(self, config: dict, context: dict) -> dict:
        """Send a WhatsApp message via Twilio.

        Config:
            to: Recipient phone number (E.164 format, e.g. "+15551234567")
            body: Message text
            from_number: Override default WhatsApp sender (optional)
            media_url: URL of media to attach (optional)
        """
        to = config.get("to", "")
        body = config.get("body", "")
        from_number = config.get("from_number", self._from_number or "")
        media_url = config.get("media_url", "")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "to": f"whatsapp:{to}",
                "from": f"whatsapp:{from_number}",
                "body": body,
                "sid": "SM_sim_whatsapp_123",
                "message": "No Twilio credentials configured — WhatsApp message simulated",
            }

        try:
            params: dict[str, str] = {
                "To": f"whatsapp:{to}",
                "From": f"whatsapp:{from_number}",
                "Body": body,
            }
            if media_url:
                params["MediaUrl"] = media_url

            data = self._api("POST", f"/Accounts/{self._account_sid}/Messages.json", params=params)
            return {
                "status": "success",
                "sid": data["sid"],
                "to": data["to"],
                "from": data["from"],
                "body": data["body"],
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_messages(self, config: dict, context: dict) -> dict:
        """Retrieve recent messages from Twilio.

        Config:
            to: Filter by recipient number (optional)
            from_number: Filter by sender number (optional)
            limit: Max results (default 20)
            date_sent: Filter by date sent, YYYY-MM-DD (optional)
        """
        limit = config.get("limit", 20)
        to = config.get("to", "")
        from_number = config.get("from_number", "")

        if not self._has_credentials:
            return {
                "status": "simulated",
                "messages": [
                    {
                        "sid": "SM_sim_001",
                        "to": "+15551234567",
                        "from": "+15559876543",
                        "body": "Your order has shipped!",
                        "status": "delivered",
                        "date_sent": "2026-03-21T14:30:00Z",
                    },
                    {
                        "sid": "SM_sim_002",
                        "to": "+15551234567",
                        "from": "+15559876543",
                        "body": "Appointment reminder: Tomorrow at 3PM",
                        "status": "delivered",
                        "date_sent": "2026-03-20T09:00:00Z",
                    },
                ],
                "message": "No Twilio credentials configured — returning simulated messages",
            }

        try:
            params: dict[str, Any] = {"PageSize": limit}
            if to:
                params["To"] = to
            if from_number:
                params["From"] = from_number
            if config.get("date_sent"):
                params["DateSent"] = config["date_sent"]

            data = self._api("GET", f"/Accounts/{self._account_sid}/Messages.json", params=params)
            messages = [
                {
                    "sid": m["sid"],
                    "to": m["to"],
                    "from": m["from"],
                    "body": m["body"],
                    "status": m["status"],
                    "date_sent": m.get("date_sent"),
                }
                for m in data.get("messages", [])
            ]
            return {"status": "success", "messages": messages}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _api(self, method: str, endpoint: str, params: dict | None = None) -> Any:
        """Make an authenticated request to the Twilio REST API."""
        import base64

        url = f"{self.API_BASE}{endpoint}"
        credentials = base64.b64encode(f"{self._account_sid}:{self._auth_token}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
        }

        if method == "GET" and params:
            url += "?" + urlencode(params)
            data = None
        elif params:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(params).encode()
        else:
            data = None

        req = Request(url, data=data, headers=headers, method=method)
        with urlopen(req) as resp:
            return json.loads(resp.read())
