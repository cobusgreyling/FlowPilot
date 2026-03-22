"""Workflow import/export in multiple formats.

Serialize and deserialize workflow graphs to JSON, YAML, and TOML.
Supports file-based and URL-based import, validation, and zip bundling.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

REQUIRED_FIELDS = ("name", "nodes")


class ExportFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"


_EXT_MAP: dict[str, ExportFormat] = {
    ".json": ExportFormat.JSON,
    ".yaml": ExportFormat.YAML,
    ".yml": ExportFormat.YAML,
    ".toml": ExportFormat.TOML,
}


def _graph_to_dict(workflow_graph: Any) -> dict:
    """Convert a workflow graph object to a plain dict."""
    if isinstance(workflow_graph, dict):
        return workflow_graph
    if hasattr(workflow_graph, "to_dict"):
        return workflow_graph.to_dict()
    if hasattr(workflow_graph, "__dict__"):
        return {k: v for k, v in workflow_graph.__dict__.items() if not k.startswith("_")}
    raise TypeError(f"Cannot convert {type(workflow_graph).__name__} to dict")


class WorkflowExporter:
    """Import and export workflow graphs in multiple formats."""

    # -- export ----------------------------------------------------------

    def export_workflow(self, workflow_graph: Any, format: ExportFormat) -> str:
        """Serialize a workflow graph to a string in the given format."""
        data = _graph_to_dict(workflow_graph)
        if format == ExportFormat.JSON:
            return json.dumps(data, indent=2, default=str)
        if format == ExportFormat.YAML:
            if not HAS_YAML:
                raise ImportError("PyYAML is required for YAML export: pip install pyyaml")
            return yaml.dump(data, default_flow_style=False, sort_keys=False)
        if format == ExportFormat.TOML:
            # tomllib is read-only; fall back to a minimal TOML serializer
            return self._to_toml(data)
        raise ValueError(f"Unsupported format: {format}")

    def export_to_file(
        self, workflow_graph: Any, path: str, format: ExportFormat | None = None
    ) -> None:
        """Export a workflow to a file, auto-detecting format from extension."""
        p = Path(path)
        if format is None:
            format = _EXT_MAP.get(p.suffix.lower())
            if format is None:
                raise ValueError(f"Cannot detect format from extension '{p.suffix}'")
        content = self.export_workflow(workflow_graph, format)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # -- import ----------------------------------------------------------

    def import_workflow(self, data: str, format: ExportFormat) -> dict:
        """Deserialize a workflow from a string."""
        if format == ExportFormat.JSON:
            return json.loads(data)
        if format == ExportFormat.YAML:
            if not HAS_YAML:
                raise ImportError("PyYAML is required for YAML import: pip install pyyaml")
            return yaml.safe_load(data)
        if format == ExportFormat.TOML:
            if tomllib is None:
                raise ImportError("tomli is required for TOML import: pip install tomli")
            return tomllib.loads(data)
        raise ValueError(f"Unsupported format: {format}")

    def import_from_file(self, path: str) -> dict:
        """Import a workflow from a file, auto-detecting format."""
        p = Path(path)
        fmt = _EXT_MAP.get(p.suffix.lower())
        if fmt is None:
            raise ValueError(f"Cannot detect format from extension '{p.suffix}'")
        content = p.read_text(encoding="utf-8")
        return self.import_workflow(content, fmt)

    def import_from_url(self, url: str) -> dict:
        """Fetch a workflow definition from a URL and import it."""
        import urllib.request

        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        # Guess format from URL path extension
        suffix = Path(url.split("?")[0]).suffix.lower()
        fmt = _EXT_MAP.get(suffix, ExportFormat.JSON)
        return self.import_workflow(raw, fmt)

    # -- validation ------------------------------------------------------

    def validate_import(self, data: dict) -> list[str]:
        """Return a list of validation errors (empty means valid)."""
        errors: list[str] = []
        if not isinstance(data, dict):
            return ["Imported data must be a dict"]
        for field in REQUIRED_FIELDS:
            if field not in data:
                errors.append(f"Missing required field: '{field}'")
        if "nodes" in data and not isinstance(data["nodes"], (list, dict)):
            errors.append("'nodes' must be a list or dict")
        return errors

    # -- bundling --------------------------------------------------------

    def bundle_workflow(
        self, workflow_graph: Any, include_templates: bool = False
    ) -> bytes:
        """Create a zip bundle containing the workflow and metadata."""
        data = _graph_to_dict(workflow_graph)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("workflow.json", json.dumps(data, indent=2, default=str))
            meta = {
                "bundled_at": datetime.now(timezone.utc).isoformat(),
                "version": data.get("version", "1.0"),
                "include_templates": include_templates,
            }
            zf.writestr("meta.json", json.dumps(meta, indent=2))
            if include_templates and "templates" in data:
                zf.writestr(
                    "templates.json",
                    json.dumps(data["templates"], indent=2, default=str),
                )
        return buf.getvalue()

    def unbundle_workflow(self, bundle_path: str) -> dict:
        """Extract and load a workflow from a zip bundle."""
        with zipfile.ZipFile(bundle_path, "r") as zf:
            workflow = json.loads(zf.read("workflow.json"))
            if "meta.json" in zf.namelist():
                workflow["_meta"] = json.loads(zf.read("meta.json"))
            if "templates.json" in zf.namelist():
                workflow["templates"] = json.loads(zf.read("templates.json"))
        return workflow

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _to_toml(data: dict, _prefix: str = "") -> str:
        """Minimal TOML serializer for flat / one-level-nested dicts."""
        lines: list[str] = []
        tables: list[tuple[str, dict]] = []
        for key, value in data.items():
            if isinstance(value, dict):
                tables.append((f"{_prefix}{key}" if _prefix else key, value))
            elif isinstance(value, list):
                lines.append(f"{key} = {json.dumps(value, default=str)}")
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            else:
                lines.append(f'{key} = "{value}"')
        for table_key, table_val in tables:
            lines.append(f"\n[{table_key}]")
            lines.append(WorkflowExporter._to_toml(table_val, f"{table_key}."))
        return "\n".join(lines)
