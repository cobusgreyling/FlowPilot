"""Workflow marketplace — discover, share, and install community templates.

Provides a local registry of workflow templates with metadata,
categories, and ratings. Templates can be installed from a remote
URL or shared as JSON files.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MarketplaceEntry:
    template_id: str
    name: str
    description: str
    author: str
    category: str
    tags: list[str]
    node_count: int
    connectors_used: list[str]
    downloads: int
    rating: float
    created_at: str
    data: dict

    def __str__(self) -> str:
        stars = "★" * int(self.rating) + "☆" * (5 - int(self.rating))
        return f"{self.name} by {self.author} {stars} ({self.downloads} downloads)"


CATEGORIES = [
    "devops",
    "communication",
    "data-pipeline",
    "monitoring",
    "customer-support",
    "content",
    "reporting",
    "security",
    "general",
]


class WorkflowMarketplace:
    """Local marketplace for workflow templates."""

    def __init__(self, db_path: str = "flowpilot.db", templates_dir: str = "templates"):
        self._db_path = db_path
        self._templates_dir = Path(templates_dir)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS marketplace (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    author TEXT NOT NULL,
                    category TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    node_count INTEGER NOT NULL,
                    connectors_used TEXT NOT NULL,
                    downloads INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                )
            """)

    def publish(self, data: dict, author: str, category: str = "general", tags: list[str] | None = None) -> str:
        """Publish a workflow template to the marketplace."""
        template_id = data.get("id", "")
        name = data.get("name", "Untitled")
        description = data.get("description", "")
        nodes = data.get("nodes", [])
        connectors = list({n.get("connector", "") for n in nodes})

        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO marketplace
                   (template_id, name, description, author, category, tags,
                    node_count, connectors_used, downloads, rating, created_at, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0.0, ?, ?)""",
                (
                    template_id, name, description, author, category,
                    json.dumps(tags or []), len(nodes), json.dumps(connectors),
                    now, json.dumps(data),
                ),
            )
        return template_id

    def search(self, query: str = "", category: str = "", limit: int = 20) -> list[MarketplaceEntry]:
        """Search the marketplace."""
        with sqlite3.connect(self._db_path) as conn:
            if query and category:
                rows = conn.execute(
                    """SELECT * FROM marketplace
                       WHERE (name LIKE ? OR description LIKE ? OR tags LIKE ?)
                       AND category = ?
                       ORDER BY downloads DESC LIMIT ?""",
                    (f"%{query}%", f"%{query}%", f"%{query}%", category, limit),
                ).fetchall()
            elif query:
                rows = conn.execute(
                    """SELECT * FROM marketplace
                       WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
                       ORDER BY downloads DESC LIMIT ?""",
                    (f"%{query}%", f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT * FROM marketplace WHERE category = ? ORDER BY downloads DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM marketplace ORDER BY downloads DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [self._row_to_entry(r) for r in rows]

    def install(self, template_id: str) -> dict | None:
        """Install a template to the local templates directory."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT data FROM marketplace WHERE template_id = ?", (template_id,)
            ).fetchone()
            if not row:
                return None

            conn.execute(
                "UPDATE marketplace SET downloads = downloads + 1 WHERE template_id = ?",
                (template_id,),
            )

        data = json.loads(row[0])
        self._templates_dir.mkdir(exist_ok=True)
        path = self._templates_dir / f"{template_id}.json"
        path.write_text(json.dumps(data, indent=2))
        return data

    def rate(self, template_id: str, score: float) -> None:
        """Rate a template (1-5 stars)."""
        score = max(1.0, min(5.0, score))
        with sqlite3.connect(self._db_path) as conn:
            # Simple average (in production you'd track individual ratings)
            row = conn.execute(
                "SELECT rating, downloads FROM marketplace WHERE template_id = ?",
                (template_id,),
            ).fetchone()
            if row:
                current_rating, count = row
                new_rating = (current_rating * max(count - 1, 0) + score) / max(count, 1)
                conn.execute(
                    "UPDATE marketplace SET rating = ? WHERE template_id = ?",
                    (round(new_rating, 2), template_id),
                )

    def get_categories(self) -> list[dict]:
        """Get categories with template counts."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) FROM marketplace GROUP BY category ORDER BY COUNT(*) DESC"
            ).fetchall()
        return [{"category": r[0], "count": r[1]} for r in rows]

    def index_local_templates(self, author: str = "FlowPilot") -> int:
        """Index all JSON files in the templates directory into the marketplace."""
        count = 0
        if not self._templates_dir.exists():
            return 0
        for f in self._templates_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                self.publish(data, author=author, category="general")
                count += 1
            except Exception:
                continue
        return count

    def _row_to_entry(self, row: tuple) -> MarketplaceEntry:
        return MarketplaceEntry(
            template_id=row[0],
            name=row[1],
            description=row[2],
            author=row[3],
            category=row[4],
            tags=json.loads(row[5]),
            node_count=row[6],
            connectors_used=json.loads(row[7]),
            downloads=row[8],
            rating=row[9],
            created_at=row[10],
            data=json.loads(row[11]),
        )
