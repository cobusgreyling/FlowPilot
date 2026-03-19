"""Cron scheduler — run workflows on a recurring schedule.

Lightweight scheduler using threading and cron expression parsing.
No external dependencies required.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ScheduledJob:
    """A scheduled workflow execution."""
    job_id: str
    cron_expr: str
    callback: Callable
    name: str = ""
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    active: bool = True


class CronScheduler:
    """Simple cron-based workflow scheduler.

    Supports standard 5-field cron expressions:
        minute hour day_of_month month day_of_week

    Examples:
        "0 9 * * *"     — every day at 9am
        "*/15 * * * *"  — every 15 minutes
        "0 0 * * 1"     — every Monday at midnight
        "30 8 1 * *"    — 8:30am on the 1st of each month
    """

    def __init__(self):
        self._jobs: dict[str, ScheduledJob] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def add_job(
        self,
        job_id: str,
        cron_expr: str,
        callback: Callable,
        name: str = "",
    ) -> ScheduledJob:
        """Schedule a new job."""
        job = ScheduledJob(
            job_id=job_id,
            cron_expr=cron_expr,
            callback=callback,
            name=name or job_id,
        )
        job.next_run = self._next_match(cron_expr)
        self._jobs[job_id] = job
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False

    def pause_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].active = False

    def resume_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].active = True

    def list_jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())

    def start(self) -> None:
        """Start the scheduler loop in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running:
            now = datetime.now()
            for job in self._jobs.values():
                if not job.active:
                    continue
                if job.next_run and now >= job.next_run:
                    try:
                        job.callback()
                    except Exception as e:
                        print(f"[scheduler] Job {job.job_id} failed: {e}")
                    job.last_run = now
                    job.run_count += 1
                    job.next_run = self._next_match(job.cron_expr)
            time.sleep(30)  # Check every 30 seconds

    def _next_match(self, cron_expr: str) -> datetime:
        """Find the next datetime matching a cron expression."""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: '{cron_expr}' (expected 5 fields)")

        minute_spec, hour_spec, dom_spec, month_spec, dow_spec = parts
        now = datetime.now()

        # Simple forward search (check each minute for next 48 hours)
        from datetime import timedelta
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(2880):  # 48 hours of minutes
            if (
                _matches(candidate.minute, minute_spec)
                and _matches(candidate.hour, hour_spec)
                and _matches(candidate.day, dom_spec)
                and _matches(candidate.month, month_spec)
                and _matches(candidate.weekday(), dow_spec, is_dow=True)
            ):
                return candidate
            candidate += timedelta(minutes=1)

        # Fallback: 24 hours from now
        return now + timedelta(hours=24)


def _matches(value: int, spec: str, is_dow: bool = False) -> bool:
    """Check if a value matches a cron field specification."""
    if spec == "*":
        return True

    # Handle */N (every N)
    if spec.startswith("*/"):
        divisor = int(spec[2:])
        return value % divisor == 0

    # Handle ranges (1-5)
    if "-" in spec:
        low, high = spec.split("-", 1)
        return int(low) <= value <= int(high)

    # Handle lists (1,3,5)
    if "," in spec:
        return value in [int(v) for v in spec.split(",")]

    # Exact match
    target = int(spec)
    if is_dow:
        # Cron uses 0=Sunday, Python uses 0=Monday
        # Convert: cron 0 (Sun) = Python 6, cron 1 (Mon) = Python 0
        target = (target - 1) % 7
    return value == target
