"""HTTP connector — generic REST API calls."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from flowpilot.connectors.base import BaseConnector


class HttpConnector(BaseConnector):
    """Generic HTTP connector for REST API calls."""

    @property
    def name(self) -> str:
        return "http"

    def get(self, config: dict, context: dict) -> dict:
        """HTTP GET request.

        Config:
            url: Target URL
            headers: Optional headers dict
        """
        return self._request("GET", config, context)

    def post(self, config: dict, context: dict) -> dict:
        """HTTP POST request.

        Config:
            url: Target URL
            headers: Optional headers dict
            body: Request body (dict or string)
        """
        return self._request("POST", config, context)

    def put(self, config: dict, context: dict) -> dict:
        """HTTP PUT request."""
        return self._request("PUT", config, context)

    def delete(self, config: dict, context: dict) -> dict:
        """HTTP DELETE request."""
        return self._request("DELETE", config, context)

    def _request(self, method: str, config: dict, context: dict) -> dict:
        url = config.get("url", "")
        headers = config.get("headers", {})
        body = config.get("body")

        if not url:
            return {"status": "error", "message": "No URL configured"}

        if not headers.get("Content-Type") and method in ("POST", "PUT"):
            headers["Content-Type"] = "application/json"

        data = None
        if body:
            if isinstance(body, dict):
                data = json.dumps(body).encode()
            else:
                data = str(body).encode()

        req = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(req) as resp:
                content = resp.read().decode()
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = content

                return {
                    "status": "success",
                    "status_code": resp.status,
                    "data": parsed,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}
