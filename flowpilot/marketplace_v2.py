"""Enhanced marketplace with ratings, reviews, search, and recommendations."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CATEGORIES = [
    "devops", "communication", "data-pipeline", "monitoring",
    "customer-support", "content", "reporting", "security", "general",
]


@dataclass
class Review:
    review_id: str
    template_id: str
    author: str
    rating: int
    comment: str
    created_at: str = ""


@dataclass
class MarketplaceStats:
    total_templates: int
    total_downloads: int
    total_reviews: int
    top_categories: list[tuple[str, int]]


class MarketplaceV2:
    """Enhanced community template marketplace."""

    def __init__(self, db_path: str = "flowpilot.db", templates_dir: str = "templates"):
        self.db_path = db_path
        self.templates_dir = templates_dir
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_v2 (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    author TEXT,
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    node_count INTEGER DEFAULT 0,
                    connectors_used TEXT DEFAULT '[]',
                    downloads INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0,
                    rating_count INTEGER DEFAULT 0,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_reviews (
                    review_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (template_id) REFERENCES marketplace_v2(template_id)
                )
            """)
            conn.commit()

    def publish(self, data: dict, author: str, category: str = "general", tags: list[str] = None) -> str:
        errors = self.validate_template(data)
        if errors:
            raise ValueError(f"Invalid template: {'; '.join(errors)}")
        template_id = uuid.uuid4().hex[:12]
        nodes = data.get("nodes", [])
        connectors = list({n.get("connector", "") for n in nodes if n.get("connector")})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO marketplace_v2 (template_id, name, description, author, category, tags, node_count, connectors_used, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (template_id, data.get("name", "Untitled"), data.get("description", ""),
                 author, category, json.dumps(tags or []), len(nodes),
                 json.dumps(connectors), json.dumps(data)),
            )
            conn.commit()
        return template_id

    def search(self, query: str = "", category: str = "", limit: int = 20) -> list[dict]:
        sql = "SELECT template_id, name, description, author, category, tags, downloads, rating, rating_count FROM marketplace_v2 WHERE 1=1"
        params = []
        if query:
            sql += " AND (name LIKE ? OR description LIKE ? OR tags LIKE ?)"
            q = f"%{query}%"
            params.extend([q, q, q])
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY downloads DESC, rating DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            return [
                {"template_id": r[0], "name": r[1], "description": r[2], "author": r[3],
                 "category": r[4], "tags": json.loads(r[5]), "downloads": r[6],
                 "rating": r[7], "rating_count": r[8]}
                for r in cursor.fetchall()
            ]

    def install(self, template_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data FROM marketplace_v2 WHERE template_id = ?", (template_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Template not found: {template_id}")
            conn.execute("UPDATE marketplace_v2 SET downloads = downloads + 1 WHERE template_id = ?", (template_id,))
            conn.commit()
        data = json.loads(row[0])
        Path(self.templates_dir).mkdir(parents=True, exist_ok=True)
        path = os.path.join(self.templates_dir, f"{template_id}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return data

    def add_review(self, template_id: str, author: str, rating: int, comment: str = "") -> str:
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be 1-5")
        review_id = uuid.uuid4().hex[:12]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO marketplace_reviews (review_id, template_id, author, rating, comment) VALUES (?, ?, ?, ?, ?)",
                (review_id, template_id, author, rating, comment),
            )
            # Update average rating
            cursor = conn.execute(
                "SELECT AVG(rating), COUNT(*) FROM marketplace_reviews WHERE template_id = ?", (template_id,),
            )
            avg, count = cursor.fetchone()
            conn.execute(
                "UPDATE marketplace_v2 SET rating = ?, rating_count = ? WHERE template_id = ?",
                (round(avg, 2), count, template_id),
            )
            conn.commit()
        return review_id

    def get_reviews(self, template_id: str, limit: int = 20) -> list[Review]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT review_id, template_id, author, rating, comment, created_at FROM marketplace_reviews WHERE template_id = ? ORDER BY created_at DESC LIMIT ?",
                (template_id, limit),
            )
            return [Review(r[0], r[1], r[2], r[3], r[4], r[5] or "") for r in cursor.fetchall()]

    def get_featured(self, limit: int = 10) -> list[dict]:
        return self.search(query="", limit=limit)

    def get_trending(self, days: int = 7) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT template_id, name, description, author, downloads, rating FROM marketplace_v2 WHERE updated_at >= ? ORDER BY downloads DESC LIMIT 20",
                (cutoff,),
            )
            return [{"template_id": r[0], "name": r[1], "description": r[2], "author": r[3], "downloads": r[4], "rating": r[5]} for r in cursor.fetchall()]

    def get_by_connector(self, connector_name: str) -> list[dict]:
        return self.search(query=connector_name)

    def get_stats(self) -> MarketplaceStats:
        with sqlite3.connect(self.db_path) as conn:
            templates = conn.execute("SELECT COUNT(*) FROM marketplace_v2").fetchone()[0]
            downloads = conn.execute("SELECT COALESCE(SUM(downloads), 0) FROM marketplace_v2").fetchone()[0]
            reviews = conn.execute("SELECT COUNT(*) FROM marketplace_reviews").fetchone()[0]
            cats = conn.execute("SELECT category, COUNT(*) as c FROM marketplace_v2 GROUP BY category ORDER BY c DESC LIMIT 5").fetchall()
        return MarketplaceStats(templates, downloads, reviews, [(r[0], r[1]) for r in cats])

    def validate_template(self, data: dict) -> list[str]:
        errors = []
        if not isinstance(data, dict):
            return ["Template must be a JSON object"]
        if not data.get("name"):
            errors.append("Missing 'name' field")
        if not data.get("nodes"):
            errors.append("Missing or empty 'nodes' list")
        if isinstance(data.get("nodes"), list):
            for i, node in enumerate(data["nodes"]):
                if not node.get("id"):
                    errors.append(f"Node {i} missing 'id'")
                if not node.get("connector"):
                    errors.append(f"Node {i} missing 'connector'")
        return errors

    def export_template(self, template_id: str, fmt: str = "json") -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data FROM marketplace_v2 WHERE template_id = ?", (template_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Template not found: {template_id}")
        data = json.loads(row[0])
        if fmt == "json":
            return json.dumps(data, indent=2)
        elif fmt == "yaml":
            try:
                import yaml
                return yaml.dump(data, default_flow_style=False)
            except ImportError:
                raise RuntimeError("PyYAML required for YAML export")
        raise ValueError(f"Unsupported format: {fmt}")

    def import_from_url(self, url: str, author: str = "imported") -> str:
        if not HAS_REQUESTS:
            raise RuntimeError("requests library required")
        resp = _requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return self.publish(data, author=author)

    def recommend(self, description: str, limit: int = 5) -> list[dict]:
        words = set(description.lower().split())
        results = self.search(limit=50)
        scored = []
        for t in results:
            t_words = set(f"{t['name']} {t['description']}".lower().split())
            overlap = len(words & t_words)
            if overlap > 0:
                scored.append((overlap, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:limit]]
