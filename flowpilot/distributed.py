"""Distributed execution engine using task queues.

Scales FlowPilot workflows across multiple workers via pluggable
task queues (in-memory for dev, Redis for production). Workers run
in threads and execute tasks asynchronously with graceful shutdown.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TaskQueue(str, Enum):
    REDIS = "redis"
    MEMORY = "memory"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskMessage:
    task_id: str
    node_id: str
    workflow_id: str
    connector: str
    action: str
    config: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: TaskStatus = TaskStatus.QUEUED


@dataclass
class TaskResult:
    task_id: str
    node_id: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    worker_id: str = ""


class InMemoryQueue:
    """Thread-safe in-process task queue for dev / single-process use."""

    def __init__(self) -> None:
        self._tasks: deque[TaskMessage] = deque()
        self._results: dict[str, TaskResult] = {}
        self._lock = threading.Lock()
        self._event = threading.Event()

    def enqueue(self, task: TaskMessage) -> None:
        with self._lock:
            self._tasks.append(task)
        self._event.set()

    def dequeue(self, timeout: float = 1.0) -> Optional[TaskMessage]:
        self._event.wait(timeout=timeout)
        with self._lock:
            if self._tasks:
                task = self._tasks.popleft()
                if not self._tasks:
                    self._event.clear()
                return task
            self._event.clear()
            return None

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        with self._lock:
            return self._results.get(task_id)

    def set_result(self, task_id: str, result: TaskResult) -> None:
        with self._lock:
            self._results[task_id] = result

    def get_pending_count(self) -> int:
        with self._lock:
            return len(self._tasks)


class RedisQueue:
    """Production queue using Redis lists (RPUSH/BLPOP) and hashes.
    Falls back to InMemoryQueue when redis is unavailable."""

    TASK_LIST = "flowpilot:tasks"
    RESULT_HASH = "flowpilot:results"

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._fallback: Optional[InMemoryQueue] = None
        url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis
            self._redis = redis.Redis.from_url(url, decode_responses=True)
            self._redis.ping()
            logger.info("Connected to Redis at %s", url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) – using InMemoryQueue", exc)
            self._redis = None
            self._fallback = InMemoryQueue()

    def _serialize(self, task: TaskMessage) -> str:
        d = asdict(task)
        d["status"] = task.status.value
        return json.dumps(d)

    def _deserialize(self, raw: str) -> TaskMessage:
        d = json.loads(raw)
        d["status"] = TaskStatus(d["status"])
        return TaskMessage(**d)

    def enqueue(self, task: TaskMessage) -> None:
        if self._fallback:
            return self._fallback.enqueue(task)
        self._redis.rpush(self.TASK_LIST, self._serialize(task))

    def dequeue(self, timeout: float = 1.0) -> Optional[TaskMessage]:
        if self._fallback:
            return self._fallback.dequeue(timeout)
        item = self._redis.blpop(self.TASK_LIST, timeout=int(max(timeout, 1)))
        if item is None:
            return None
        return self._deserialize(item[1])

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        if self._fallback:
            return self._fallback.get_result(task_id)
        raw = self._redis.hget(self.RESULT_HASH, task_id)
        if raw is None:
            return None
        d = json.loads(raw)
        d["status"] = TaskStatus(d["status"])
        return TaskResult(**d)

    def set_result(self, task_id: str, result: TaskResult) -> None:
        if self._fallback:
            return self._fallback.set_result(task_id, result)
        d = asdict(result)
        d["status"] = result.status.value
        self._redis.hset(self.RESULT_HASH, task_id, json.dumps(d))

    def get_pending_count(self) -> int:
        if self._fallback:
            return self._fallback.get_pending_count()
        return self._redis.llen(self.TASK_LIST)


class Worker:
    """Consumes tasks from a queue in a daemon thread."""

    HEARTBEAT_INTERVAL = 5.0

    def __init__(self, queue: InMemoryQueue | RedisQueue, connectors: dict,
                 worker_id: str = "") -> None:
        self.queue = queue
        self.connectors = connectors
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._hb_thread: Optional[threading.Thread] = None
        self.tasks_processed = 0
        self.errors = 0
        self.started_at: Optional[float] = None

    def start(self) -> None:
        self._running = True
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, name=self.worker_id, daemon=True)
        self._thread.start()
        self._hb_thread = threading.Thread(
            target=self._heartbeat, name=f"{self.worker_id}-hb", daemon=True)
        self._hb_thread.start()
        logger.info("Worker %s started", self.worker_id)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._hb_thread:
            self._hb_thread.join(timeout=2)
        logger.info("Worker %s stopped", self.worker_id)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while self._running:
                task = self.queue.dequeue(timeout=1.0)
                if task is None:
                    continue
                result = loop.run_until_complete(self.execute_task(task))
                self.queue.set_result(task.task_id, result)
        finally:
            loop.close()

    async def execute_task(self, task: TaskMessage) -> TaskResult:
        start = time.monotonic()
        try:
            connector = self.connectors.get(task.connector)
            if connector is None:
                raise ValueError(f"Unknown connector: {task.connector}")
            action_fn = getattr(connector, task.action, None)
            if action_fn is None:
                raise AttributeError(
                    f"Connector {task.connector!r} has no action {task.action!r}")
            if asyncio.iscoroutinefunction(action_fn):
                res = await action_fn(**task.config)
            else:
                res = action_fn(**task.config)
            self.tasks_processed += 1
            ms = round((time.monotonic() - start) * 1000, 2)
            return TaskResult(task_id=task.task_id, node_id=task.node_id,
                              status=TaskStatus.COMPLETED, result=res,
                              duration_ms=ms, worker_id=self.worker_id)
        except Exception as exc:
            self.errors += 1
            self.tasks_processed += 1
            ms = round((time.monotonic() - start) * 1000, 2)
            logger.exception("Task %s failed on %s", task.task_id, self.worker_id)
            return TaskResult(task_id=task.task_id, node_id=task.node_id,
                              status=TaskStatus.FAILED, error=str(exc),
                              duration_ms=ms, worker_id=self.worker_id)

    def _heartbeat(self) -> None:
        while self._running:
            logger.debug("Heartbeat %s – processed=%d errors=%d",
                         self.worker_id, self.tasks_processed, self.errors)
            time.sleep(self.HEARTBEAT_INTERVAL)


class DistributedEngine:
    """Decomposes workflow graphs into queued tasks and manages worker threads."""

    def __init__(self, queue_type: TaskQueue = TaskQueue.MEMORY,
                 connectors: dict | None = None, num_workers: int = 4) -> None:
        self.connectors = connectors or {}
        self.num_workers = num_workers
        self.queue: InMemoryQueue | RedisQueue = (
            RedisQueue() if queue_type == TaskQueue.REDIS else InMemoryQueue()
        )
        self._workers: list[Worker] = []
        self._workflow_tasks: dict[str, list[str]] = {}
        self._task_meta: dict[str, TaskMessage] = {}
        self._lock = threading.Lock()

    def start_workers(self) -> None:
        for i in range(self.num_workers):
            w = Worker(self.queue, self.connectors, worker_id=f"worker-{i}")
            w.start()
            self._workers.append(w)
        logger.info("Started %d workers", self.num_workers)

    def stop_workers(self) -> None:
        for w in self._workers:
            w.stop()
        self._workers.clear()
        logger.info("All workers stopped")

    def submit_workflow(self, workflow_graph: dict) -> str:
        """Decompose graph into tasks, enqueue root nodes, return workflow_id."""
        workflow_id = uuid.uuid4().hex
        nodes = workflow_graph.get("nodes", [])
        task_ids: list[str] = []
        node_task_map: dict[str, str] = {}
        for node in nodes:
            task_id = uuid.uuid4().hex
            node_task_map[node["id"]] = task_id
            task = TaskMessage(
                task_id=task_id, node_id=node["id"], workflow_id=workflow_id,
                connector=node["connector"], action=node["action"],
                config=node.get("config", {}), context=node.get("context", {}))
            task_ids.append(task_id)
            with self._lock:
                self._task_meta[task_id] = task
        with self._lock:
            self._workflow_tasks[workflow_id] = task_ids
        # Enqueue only root tasks; dependent tasks stay tracked until deps resolve
        for node in nodes:
            if not node.get("depends_on", []):
                self.queue.enqueue(self._task_meta[node_task_map[node["id"]]])
        logger.info("Submitted workflow %s (%d tasks)", workflow_id, len(task_ids))
        return workflow_id

    def get_workflow_status(self, workflow_id: str) -> dict:
        with self._lock:
            task_ids = self._workflow_tasks.get(workflow_id, [])
        statuses: dict[str, str] = {}
        for tid in task_ids:
            res = self.queue.get_result(tid)
            if res:
                statuses[tid] = res.status.value
            else:
                meta = self._task_meta.get(tid)
                statuses[tid] = meta.status.value if meta else TaskStatus.QUEUED.value
        count = lambda v: sum(1 for s in statuses.values() if s == v)
        return {"workflow_id": workflow_id, "total": len(task_ids),
                "completed": count(TaskStatus.COMPLETED.value),
                "failed": count(TaskStatus.FAILED.value),
                "running": count(TaskStatus.RUNNING.value),
                "queued": count(TaskStatus.QUEUED.value),
                "cancelled": count(TaskStatus.CANCELLED.value),
                "tasks": statuses}

    def cancel_workflow(self, workflow_id: str) -> int:
        with self._lock:
            task_ids = self._workflow_tasks.get(workflow_id, [])
        cancelled = 0
        for tid in task_ids:
            if self.queue.get_result(tid) is None:
                self.queue.set_result(tid, TaskResult(
                    task_id=tid, node_id=self._task_meta[tid].node_id,
                    status=TaskStatus.CANCELLED, error="Cancelled by user",
                    worker_id="engine"))
                cancelled += 1
        logger.info("Cancelled %d tasks for workflow %s", cancelled, workflow_id)
        return cancelled

    def get_worker_stats(self) -> list[dict]:
        now = time.time()
        return [{"worker_id": w.worker_id, "tasks_processed": w.tasks_processed,
                 "errors": w.errors,
                 "uptime_s": round(now - w.started_at, 1) if w.started_at else 0.0,
                 "alive": w._running} for w in self._workers]
