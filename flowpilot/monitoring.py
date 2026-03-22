"""Real-time WebSocket execution monitoring.

Provides a pub/sub event bus, a FastAPI-based WebSocket server for live
monitoring, and a dashboard data aggregator. Falls back gracefully when
FastAPI or websockets are not installed.
"""
from __future__ import annotations

import asyncio, json, logging, threading, time, uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_SKIPPED = "node_skipped"
    NODE_RETRYING = "node_retrying"
    APPROVAL_WAITING = "approval_waiting"
    RATE_LIMITED = "rate_limited"
    HEALTH_CHECK = "health_check"


@dataclass
class MonitorEvent:
    """A single monitoring event emitted during workflow execution."""
    event_type: EventType
    workflow_id: str
    run_id: str
    node_id: Optional[str] = None
    status: Optional[str] = None
    message: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return json.dumps(d)


class EventBus:
    """In-process pub/sub bus for monitor events (thread-safe ring buffer)."""

    def __init__(self, buffer_size: int = 500) -> None:
        self._subscribers: Dict[str, Callable[[MonitorEvent], None]] = {}
        self._recent: deque[MonitorEvent] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[MonitorEvent], None]) -> str:
        sub_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def publish(self, event: MonitorEvent) -> None:
        with self._lock:
            self._recent.append(event)
            subscribers = list(self._subscribers.values())
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                logger.debug("Subscriber callback failed", exc_info=True)

    def get_recent(self, limit: int = 50) -> List[MonitorEvent]:
        with self._lock:
            items = list(self._recent)
        return items[-limit:]


# Graceful import of optional dependencies
try:
    from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False


class MonitoringServer:
    """WebSocket + REST server for live workflow monitoring.

    Falls back to a no-op if FastAPI/uvicorn are not installed.
    """

    def __init__(self, event_bus: EventBus, host: str = "127.0.0.1", port: int = 8400) -> None:
        self.event_bus = event_bus
        self.host, self.port = host, port
        self._active_workflows: Dict[str, dict] = {}
        self._clients: Set = set()
        self._stats = {"events_published": 0, "start_time": time.time()}
        self._thread: Optional[threading.Thread] = None
        self._sub_id: Optional[str] = None
        self._app: Optional[Any] = None
        if _HAS_FASTAPI:
            self._app = self._build_app()

    def _build_app(self) -> "FastAPI":
        app = FastAPI(title="FlowPilot Monitor", version="0.1.0")

        @app.websocket("/ws/monitor")
        async def ws_monitor(
            ws: WebSocket,
            workflow_id: Optional[str] = Query(None),
            event_types: Optional[str] = Query(None),
        ):
            await ws.accept()
            self._clients.add(ws)
            type_filter = {t.strip() for t in event_types.split(",")} if event_types else None
            queue: asyncio.Queue[MonitorEvent] = asyncio.Queue()

            def _enqueue(evt: MonitorEvent) -> None:
                if workflow_id and evt.workflow_id != workflow_id:
                    return
                if type_filter and evt.event_type.value not in type_filter:
                    return
                try:
                    queue.put_nowait(evt)
                except asyncio.QueueFull:
                    pass

            sub_id = self.event_bus.subscribe(_enqueue)
            try:
                while True:
                    evt = await queue.get()
                    await ws.send_text(evt.to_json())
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.debug("WebSocket error", exc_info=True)
            finally:
                self.event_bus.unsubscribe(sub_id)
                self._clients.discard(ws)

        @app.get("/api/monitor/events")
        async def get_events(limit: int = Query(50, ge=1, le=500)):
            events = self.event_bus.get_recent(limit)
            return JSONResponse([json.loads(e.to_json()) for e in events])

        @app.get("/api/monitor/active")
        async def get_active():
            return JSONResponse(list(self._active_workflows.values()))

        @app.get("/api/monitor/stats")
        async def get_stats():
            uptime = time.time() - self._stats["start_time"]
            epm = self._stats["events_published"] / (uptime / 60.0) if uptime > 0 else 0.0
            return JSONResponse({
                "events_per_minute": round(epm, 2),
                "active_workflows": len(self._active_workflows),
                "connected_clients": len(self._clients),
                "uptime_seconds": round(uptime, 1),
            })

        return app

    def _on_event(self, event: MonitorEvent) -> None:
        self._stats["events_published"] += 1
        wid = event.workflow_id
        if event.event_type == EventType.WORKFLOW_STARTED:
            self._active_workflows[wid] = {
                "workflow_id": wid, "run_id": event.run_id, "started_at": event.timestamp,
            }
        elif event.event_type in (EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_FAILED):
            self._active_workflows.pop(wid, None)

    def start(self) -> None:
        if not _HAS_FASTAPI:
            logger.warning("FastAPI/uvicorn not installed — monitoring server disabled")
            return
        self._sub_id = self.event_bus.subscribe(self._on_event)
        self._thread = threading.Thread(
            target=uvicorn.run,
            kwargs={"app": self._app, "host": self.host, "port": self.port, "log_level": "warning"},
            daemon=True,
        )
        self._thread.start()
        logger.info("Monitoring server started on %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self._sub_id:
            self.event_bus.unsubscribe(self._sub_id)
            self._sub_id = None
        logger.info("Monitoring server stopped")


class DashboardData:
    """Builds a combined dashboard snapshot from multiple subsystems."""

    def __init__(self, event_bus: EventBus, history: Any = None,
                 sla_tracker: Any = None, rate_limiter: Any = None) -> None:
        self.event_bus = event_bus
        self.history = history
        self.sla_tracker = sla_tracker
        self.rate_limiter = rate_limiter

    def _success_rate(self, hours: int) -> Optional[float]:
        if self.history is None:
            return None
        try:
            runs = self.history.query_runs(last_hours=hours)
            if not runs:
                return None
            ok = sum(1 for r in runs if r.status == "success")
            return round(ok / len(runs) * 100, 2)
        except Exception:
            return None

    def _nodes_executed_today(self) -> int:
        return sum(1 for e in self.event_bus.get_recent(500)
                   if e.event_type == EventType.NODE_COMPLETED)

    def _avg_duration_ms(self) -> Optional[float]:
        if self.history is None:
            return None
        try:
            runs = self.history.query_runs(last_hours=24)
            durations = [r.duration_ms for r in runs if r.duration_ms > 0]
            return round(sum(durations) / len(durations), 1) if durations else 0.0
        except Exception:
            return None

    def get_dashboard_snapshot(self) -> dict:
        recent = self.event_bus.get_recent(100)
        # Derive active workflows from event stream
        seen_wf: Dict[str, dict] = {}
        for evt in recent:
            if evt.event_type == EventType.WORKFLOW_STARTED:
                seen_wf[evt.workflow_id] = {
                    "workflow_id": evt.workflow_id, "run_id": evt.run_id,
                    "started_at": evt.timestamp,
                }
            elif evt.event_type in (EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_FAILED):
                seen_wf.pop(evt.workflow_id, None)

        sla_statuses: List[dict] = []
        if self.sla_tracker is not None:
            try:
                sla_statuses = [
                    {"workflow_id": s.workflow_id, "status": s.status,
                     "current_rate": s.current_rate, "sla_target": s.sla_target}
                    for s in self.sla_tracker.all_statuses()
                ]
            except Exception:
                pass

        rl_stats: dict = {}
        if self.rate_limiter is not None:
            try:
                rl_stats = self.rate_limiter.stats()
            except Exception:
                pass

        return {
            "active_workflows": list(seen_wf.values()),
            "recent_events": [json.loads(e.to_json()) for e in recent[-20:]],
            "sla_statuses": sla_statuses,
            "rate_limiter_stats": rl_stats,
            "success_rate_1h": self._success_rate(1),
            "success_rate_24h": self._success_rate(24),
            "nodes_executed_today": self._nodes_executed_today(),
            "avg_duration_ms": self._avg_duration_ms(),
        }
