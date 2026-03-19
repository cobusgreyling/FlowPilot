"""Reporting module — generate workflow execution reports.

Produces daily/weekly summaries, SLA compliance reports, connector
usage analysis, and trend data. Exports to Markdown, JSON, and CSV.
Supports scheduled delivery via Slack, email, or file.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class ReportSection:
    title: str
    content: str
    data: dict = field(default_factory=dict)


@dataclass
class Report:
    title: str
    generated_at: str
    period_start: str
    period_end: str
    sections: list[ReportSection] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            f"",
            f"**Generated:** {self.generated_at}",
            f"**Period:** {self.period_start} to {self.period_end}",
            f"",
            "---",
            "",
        ]
        for section in self.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "title": self.title,
            "generated_at": self.generated_at,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "sections": [
                {"title": s.title, "content": s.content, "data": s.data}
                for s in self.sections
            ],
        }, indent=2)

    def to_csv(self) -> str:
        """Export tabular data from all sections as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "metric", "value"])
        for section in self.sections:
            for key, value in section.data.items():
                writer.writerow([section.title, key, value])
        return output.getvalue()


class ReportGenerator:
    """Generate reports from FlowPilot execution data."""

    def __init__(self, db_path: str = "flowpilot.db"):
        self._db_path = db_path

    def execution_summary(self, days: int = 7) -> Report:
        """Generate a workflow execution summary report."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        period_label = "Daily" if days <= 1 else "Weekly" if days <= 7 else "Monthly"

        runs = self._get_runs(cutoff)
        report = Report(
            title=f"FlowPilot {period_label} Execution Report",
            generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            period_start=cutoff.strftime("%Y-%m-%d"),
            period_end=now.strftime("%Y-%m-%d"),
        )

        # Overview
        total = len(runs)
        successes = sum(1 for r in runs if r["status"] == "success")
        failures = total - successes
        rate = round(successes / total * 100, 1) if total > 0 else 0
        durations = [r["duration_ms"] for r in runs]
        avg_dur = int(sum(durations) / len(durations)) if durations else 0
        max_dur = max(durations) if durations else 0
        min_dur = min(durations) if durations else 0

        overview_data = {
            "total_runs": total,
            "successes": successes,
            "failures": failures,
            "success_rate_pct": rate,
            "avg_duration_ms": avg_dur,
            "min_duration_ms": min_dur,
            "max_duration_ms": max_dur,
        }

        overview_md = (
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Total Runs | {total} |\n"
            f"| Successes | {successes} |\n"
            f"| Failures | {failures} |\n"
            f"| Success Rate | {rate}% |\n"
            f"| Avg Duration | {avg_dur}ms |\n"
            f"| Min Duration | {min_dur}ms |\n"
            f"| Max Duration | {max_dur}ms |\n"
        )
        report.sections.append(ReportSection("Overview", overview_md, overview_data))

        # Per-workflow breakdown
        workflow_stats = self._group_by_workflow(runs)
        if workflow_stats:
            wf_lines = ["| Workflow | Runs | Success Rate | Avg Duration | Failures |",
                        "|----------|------|-------------|--------------|----------|"]
            wf_data = {}
            for wf_name, stats in sorted(workflow_stats.items(), key=lambda x: x[1]["total"], reverse=True):
                wf_rate = round(stats["successes"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
                wf_avg = int(stats["total_duration"] / stats["total"]) if stats["total"] > 0 else 0
                wf_lines.append(
                    f"| {wf_name} | {stats['total']} | {wf_rate}% | {wf_avg}ms | {stats['failures']} |"
                )
                wf_data[wf_name] = {"runs": stats["total"], "success_rate": wf_rate, "avg_duration_ms": wf_avg}

            report.sections.append(ReportSection(
                "Per-Workflow Breakdown", "\n".join(wf_lines), wf_data
            ))

        # Failure analysis
        failed_runs = [r for r in runs if r["status"] != "success"]
        if failed_runs:
            fail_lines = ["| Time | Workflow | Failed Nodes | Duration |",
                         "|------|----------|-------------|----------|"]
            for r in failed_runs[:20]:
                fail_lines.append(
                    f"| {r['started_at'][:16]} | {r['workflow_name']} "
                    f"| {r['nodes_failed']} | {r['duration_ms']}ms |"
                )
            report.sections.append(ReportSection(
                "Failure Analysis",
                "\n".join(fail_lines),
                {"failed_count": len(failed_runs)},
            ))

        # Slowest executions
        if runs:
            slowest = sorted(runs, key=lambda r: r["duration_ms"], reverse=True)[:10]
            slow_lines = ["| Workflow | Duration | Status | Nodes |",
                         "|----------|----------|--------|-------|"]
            for r in slowest:
                slow_lines.append(
                    f"| {r['workflow_name']} | {r['duration_ms']}ms "
                    f"| {r['status']} | {r['nodes_succeeded']}/{r['nodes_total']} |"
                )
            report.sections.append(ReportSection(
                "Slowest Executions (Top 10)", "\n".join(slow_lines), {}
            ))

        # Trend: runs per day
        if runs and days > 1:
            daily_counts = Counter()
            for r in runs:
                day = r["started_at"][:10]
                daily_counts[day] += 1

            trend_lines = ["| Date | Runs |", "|------|------|"]
            for day in sorted(daily_counts.keys()):
                trend_lines.append(f"| {day} | {daily_counts[day]} |")
            report.sections.append(ReportSection(
                "Daily Trend", "\n".join(trend_lines), dict(daily_counts)
            ))

        return report

    def connector_usage(self, days: int = 7) -> Report:
        """Generate a connector usage report."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        runs = self._get_runs(cutoff)
        report = Report(
            title="FlowPilot Connector Usage Report",
            generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            period_start=cutoff.strftime("%Y-%m-%d"),
            period_end=now.strftime("%Y-%m-%d"),
        )

        # Parse connector usage from run details
        connector_counts: Counter = Counter()
        connector_failures: Counter = Counter()

        for r in runs:
            details = r.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (json.JSONDecodeError, TypeError):
                    details = {}

            results = details.get("results", {})
            for node_id, result in results.items():
                if isinstance(result, dict):
                    conn = result.get("connector", "unknown")
                    connector_counts[conn] += 1
                    if result.get("status") == "error":
                        connector_failures[conn] += 1

        # If no detailed connector data, estimate from workflow definitions
        if not connector_counts:
            for r in runs:
                details = r.get("details", {})
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except (json.JSONDecodeError, TypeError):
                        continue
                # Count nodes from the run's node totals
                connector_counts["estimated_total"] += r.get("nodes_total", 0)

        if connector_counts:
            total_calls = sum(connector_counts.values())
            lines = ["| Connector | Calls | % of Total | Failures | Failure Rate |",
                     "|-----------|-------|-----------|----------|-------------|"]
            conn_data = {}
            for conn, count in connector_counts.most_common():
                pct = round(count / total_calls * 100, 1) if total_calls > 0 else 0
                fails = connector_failures.get(conn, 0)
                fail_rate = round(fails / count * 100, 1) if count > 0 else 0
                lines.append(f"| {conn} | {count} | {pct}% | {fails} | {fail_rate}% |")
                conn_data[conn] = {"calls": count, "failures": fails}

            report.sections.append(ReportSection(
                "Connector Usage", "\n".join(lines), conn_data
            ))
        else:
            report.sections.append(ReportSection(
                "Connector Usage", "No connector usage data available for this period.", {}
            ))

        # Summary stats
        summary_data = {
            "total_workflows": len(runs),
            "unique_connectors": len(connector_counts),
            "total_connector_calls": sum(connector_counts.values()),
            "total_connector_failures": sum(connector_failures.values()),
        }
        summary_lines = [f"- **Total workflow runs:** {summary_data['total_workflows']}",
                        f"- **Unique connectors used:** {summary_data['unique_connectors']}",
                        f"- **Total connector calls:** {summary_data['total_connector_calls']}",
                        f"- **Total connector failures:** {summary_data['total_connector_failures']}"]
        report.sections.append(ReportSection("Summary", "\n".join(summary_lines), summary_data))

        return report

    def sla_compliance(self, days: int = 7) -> Report:
        """Generate an SLA compliance report."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        report = Report(
            title="FlowPilot SLA Compliance Report",
            generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            period_start=cutoff.strftime("%Y-%m-%d"),
            period_end=now.strftime("%Y-%m-%d"),
        )

        # Get SLA targets
        try:
            with sqlite3.connect(self._db_path) as conn:
                targets = conn.execute(
                    "SELECT workflow_id, workflow_name, target_pct, window_hours FROM sla_targets"
                ).fetchall()
        except Exception:
            targets = []

        if not targets:
            report.sections.append(ReportSection(
                "SLA Status", "No SLA targets configured. Use `flowpilot sla --set` to add targets.", {}
            ))
            return report

        lines = ["| Workflow | Target | Current | Error Budget | Status |",
                 "|----------|--------|---------|-------------|--------|"]
        sla_data = {}

        for wf_id, wf_name, target_pct, window_hours in targets:
            window_cutoff = (now - timedelta(hours=window_hours)).isoformat()
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    """SELECT COUNT(*), SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)
                       FROM runs WHERE workflow_id = ? AND started_at >= ?""",
                    (wf_id, window_cutoff),
                ).fetchone()

            total = row[0] or 0
            successes = row[1] or 0
            failures = total - successes
            current_rate = round(successes / total * 100, 1) if total > 0 else 100.0

            budget_total = (100 - target_pct) / 100 * total if total > 0 else 0
            budget_remaining = max(0, budget_total - failures)
            budget_pct = round(budget_remaining / budget_total * 100, 0) if budget_total > 0 else 100

            if current_rate >= target_pct:
                status = "Healthy"
            elif budget_remaining > 0:
                status = "Warning"
            else:
                status = "BREACHED"

            lines.append(
                f"| {wf_name} | {target_pct}% | {current_rate}% | {budget_pct}% | {status} |"
            )
            sla_data[wf_name] = {
                "target": target_pct,
                "current": current_rate,
                "budget_remaining_pct": budget_pct,
                "status": status,
            }

        report.sections.append(ReportSection("SLA Status", "\n".join(lines), sla_data))

        # Breach history
        breached = [name for name, d in sla_data.items() if d["status"] == "BREACHED"]
        if breached:
            breach_md = "\n".join(f"- **{name}** — error budget exhausted" for name in breached)
            report.sections.append(ReportSection(
                "Active Breaches", breach_md, {"breached_workflows": breached}
            ))

        return report

    def full_report(self, days: int = 7) -> Report:
        """Generate a comprehensive report combining all report types."""
        exec_report = self.execution_summary(days)
        conn_report = self.connector_usage(days)
        sla_report = self.sla_compliance(days)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        combined = Report(
            title="FlowPilot Comprehensive Report",
            generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            period_start=cutoff.strftime("%Y-%m-%d"),
            period_end=now.strftime("%Y-%m-%d"),
        )

        combined.sections.extend(exec_report.sections)
        combined.sections.extend(conn_report.sections)
        combined.sections.extend(sla_report.sections)

        return combined

    def export(self, report: Report, path: str, format: str = "markdown") -> str:
        """Export a report to a file.

        Args:
            report: The report to export
            path: File path
            format: "markdown", "json", or "csv"
        """
        if format == "json":
            content = report.to_json()
        elif format == "csv":
            content = report.to_csv()
        else:
            content = report.to_markdown()

        Path(path).write_text(content)
        return path

    def deliver(self, report: Report, channel: str, config: dict | None = None) -> dict:
        """Deliver a report via a connector.

        Args:
            report: The report to deliver
            channel: "slack", "email", or "file"
            config: Channel-specific config (channel name, email address, file path)
        """
        config = config or {}
        content = report.to_markdown()

        if channel == "slack":
            from flowpilot.connectors.slack import SlackConnector
            connector = SlackConnector()
            return connector.send_message(
                config={"channel": config.get("channel", "#reports"), "text": content},
                context={},
            )
        elif channel == "email":
            from flowpilot.connectors.email_connector import EmailConnector
            connector = EmailConnector()
            return connector.send_email(
                config={
                    "to": config.get("to", ""),
                    "subject": report.title,
                    "body": content,
                },
                context={},
            )
        elif channel == "file":
            fmt = config.get("format", "markdown")
            path = config.get("path", f"reports/{report.title.lower().replace(' ', '_')}.md")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.export(report, path, fmt)
            return {"status": "success", "path": path, "format": fmt}
        else:
            return {"status": "error", "message": f"Unknown delivery channel: {channel}"}

    def _get_runs(self, cutoff: datetime) -> list[dict]:
        """Fetch runs from the history database."""
        cutoff_str = cutoff.isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """SELECT run_id, workflow_id, workflow_name, status,
                              nodes_total, nodes_succeeded, nodes_failed, nodes_skipped,
                              duration_ms, started_at, details
                       FROM runs WHERE started_at >= ?
                       ORDER BY started_at DESC""",
                    (cutoff_str,),
                ).fetchall()
        except Exception:
            return []

        return [
            {
                "run_id": r[0], "workflow_id": r[1], "workflow_name": r[2],
                "status": r[3], "nodes_total": r[4], "nodes_succeeded": r[5],
                "nodes_failed": r[6], "nodes_skipped": r[7], "duration_ms": r[8],
                "started_at": r[9], "details": r[10],
            }
            for r in rows
        ]

    def _group_by_workflow(self, runs: list[dict]) -> dict:
        """Group run stats by workflow name."""
        groups: dict[str, dict] = {}
        for r in runs:
            name = r["workflow_name"]
            if name not in groups:
                groups[name] = {"total": 0, "successes": 0, "failures": 0, "total_duration": 0}
            groups[name]["total"] += 1
            groups[name]["total_duration"] += r["duration_ms"]
            if r["status"] == "success":
                groups[name]["successes"] += 1
            else:
                groups[name]["failures"] += 1
        return groups
