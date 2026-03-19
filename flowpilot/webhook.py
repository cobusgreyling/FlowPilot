"""Webhook trigger server — receive events and trigger workflows.

Lightweight FastAPI server that listens for incoming webhooks and
maps them to registered workflow graphs for execution.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import JSONResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class WebhookServer:
    """Webhook trigger server for FlowPilot workflows.

    Registers webhook endpoints that trigger workflow execution
    when external services send events.

    Usage:
        server = WebhookServer()
        server.register("/github", handler_fn, secret="my_secret")
        server.run(port=8081)
    """

    def __init__(self):
        self._routes: dict[str, WebhookRoute] = {}
        self._event_log: list[dict] = []

        if HAS_FASTAPI:
            self._app = FastAPI(title="FlowPilot Webhooks")
            self._setup_routes()
        else:
            self._app = None

    def register(
        self,
        path: str,
        handler: Callable,
        secret: str | None = None,
        name: str = "",
        response_mode: bool = False,
    ) -> str:
        """Register a webhook endpoint.

        Args:
            path: URL path (e.g., "/github")
            handler: Callback function(payload: dict) -> dict
            secret: Optional HMAC secret for signature verification
            name: Human-readable name for this webhook
            response_mode: If True, return workflow output as the HTTP response
        """
        route_id = str(uuid.uuid4())[:8]
        self._routes[path] = WebhookRoute(
            route_id=route_id,
            path=path,
            handler=handler,
            secret=secret,
            name=name or path.strip("/"),
            response_mode=response_mode,
        )
        return route_id

    def unregister(self, path: str) -> bool:
        if path in self._routes:
            del self._routes[path]
            return True
        return False

    def list_routes(self) -> list[dict]:
        return [
            {"path": r.path, "name": r.name, "route_id": r.route_id, "hit_count": r.hit_count}
            for r in self._routes.values()
        ]

    def get_event_log(self, limit: int = 50) -> list[dict]:
        return self._event_log[-limit:]

    def run(self, host: str = "0.0.0.0", port: int = 8081) -> None:
        """Start the webhook server."""
        if not HAS_FASTAPI:
            print("FastAPI not installed. Install with: pip install fastapi uvicorn")
            print("Webhook routes registered:")
            for path, route in self._routes.items():
                print(f"  POST {path} → {route.name}")
            return

        import uvicorn
        uvicorn.run(self._app, host=host, port=port)

    def _setup_routes(self) -> None:
        if not self._app:
            return

        @self._app.post("/{path:path}")
        async def handle_webhook(path: str, request: Request):
            full_path = f"/{path}"
            route = self._routes.get(full_path)
            if not route:
                raise HTTPException(404, f"No webhook registered at {full_path}")

            body = await request.body()
            payload = json.loads(body) if body else {}

            # Verify signature if secret is configured
            if route.secret:
                signature = request.headers.get("X-Hub-Signature-256", "")
                if not self._verify_signature(body, route.secret, signature):
                    raise HTTPException(401, "Invalid webhook signature")

            # Execute handler
            route.hit_count += 1
            event = {
                "event_id": str(uuid.uuid4())[:8],
                "path": full_path,
                "route_name": route.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload_keys": list(payload.keys()),
            }

            try:
                result = route.handler(payload)
                event["status"] = "success"
                self._event_log.append(event)
                if route.response_mode:
                    return JSONResponse(result if isinstance(result, dict) else {"result": result})
                return JSONResponse({"status": "ok", "result": result})
            except Exception as e:
                event["status"] = "error"
                event["error"] = str(e)
                self._event_log.append(event)
                raise HTTPException(500, str(e))

        @self._app.get("/")
        async def health():
            return {
                "service": "FlowPilot Webhooks",
                "routes": len(self._routes),
                "events_processed": sum(r.hit_count for r in self._routes.values()),
            }

    def _verify_signature(self, body: bytes, secret: str, signature: str) -> bool:
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


class WebhookRoute:
    """Internal representation of a registered webhook route."""

    def __init__(
        self,
        route_id: str,
        path: str,
        handler: Callable,
        secret: str | None = None,
        name: str = "",
        response_mode: bool = False,
    ):
        self.route_id = route_id
        self.path = path
        self.handler = handler
        self.secret = secret
        self.name = name
        self.response_mode = response_mode
        self.hit_count = 0
