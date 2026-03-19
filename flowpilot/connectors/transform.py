"""Transform connector — data shaping operations between workflow steps."""

from __future__ import annotations

import json
import re
from typing import Any

from flowpilot.connectors.base import BaseConnector


class TransformConnector(BaseConnector):
    """Data transformation connector for shaping data between nodes."""

    @property
    def name(self) -> str:
        return "transform"

    def filter(self, config: dict, context: dict) -> dict:
        """Filter a list based on a field condition.

        Config:
            input_key: Context key containing the list
            field: Field name to filter on
            operator: "equals", "contains", "gt", "lt"
            value: Value to compare against
        """
        input_key = config.get("input_key", "")
        data = _resolve_input(input_key, context)
        if not isinstance(data, list):
            return {"status": "error", "message": f"Input is not a list"}

        field = config.get("field", "")
        operator = config.get("operator", "equals")
        value = config.get("value")

        filtered = []
        for item in data:
            item_val = item.get(field) if isinstance(item, dict) else item
            if _compare(item_val, operator, value):
                filtered.append(item)

        return {"status": "success", "data": filtered, "count": len(filtered)}

    def map(self, config: dict, context: dict) -> dict:
        """Extract a single field from each item in a list.

        Config:
            input_key: Context key containing the list
            field: Field to extract
        """
        input_key = config.get("input_key", "")
        field = config.get("field", "")
        data = _resolve_input(input_key, context)

        if not isinstance(data, list):
            return {"status": "error", "message": "Input is not a list"}

        mapped = [item.get(field, "") if isinstance(item, dict) else item for item in data]
        return {"status": "success", "data": mapped}

    def format_template(self, config: dict, context: dict) -> dict:
        """Format data using a template string.

        Config:
            template: String with {{key}} placeholders
        """
        template = config.get("template", "{{result}}")
        result = template

        # Replace {{key}} placeholders with context values
        for key, value in context.items():
            if isinstance(value, dict):
                text = value.get("data") or value.get("text") or value.get("message") or json.dumps(value)
                if not isinstance(text, str):
                    text = json.dumps(text)
            else:
                text = str(value)
            result = result.replace(f"{{{{{key}}}}}", text)

        return {"status": "success", "text": result}

    def extract_field(self, config: dict, context: dict) -> dict:
        """Extract a nested field from context data.

        Config:
            input_key: Context key
            path: Dot-separated path (e.g., "data.items.0.title")
        """
        input_key = config.get("input_key", "")
        path = config.get("path", "")
        data = _resolve_input(input_key, context)

        for part in path.split("."):
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, list) and part.isdigit():
                idx = int(part)
                data = data[idx] if idx < len(data) else None
            else:
                data = None
                break

        return {"status": "success", "data": data}

    def join(self, config: dict, context: dict) -> dict:
        """Join multiple context values into a single string.

        Config:
            keys: List of context keys to join
            separator: Join separator (default newline)
        """
        keys = config.get("keys", list(context.keys()))
        separator = config.get("separator", "\n")

        parts = []
        for key in keys:
            val = context.get(key)
            if isinstance(val, dict):
                parts.append(val.get("text") or val.get("data") or str(val))
            elif val is not None:
                parts.append(str(val))

        return {"status": "success", "text": separator.join(parts)}


def _resolve_input(key: str, context: dict) -> Any:
    """Resolve an input key from context, handling nested dicts."""
    val = context.get(key)
    if isinstance(val, dict):
        return val.get("data") or val.get("items") or val
    return val


def _compare(item_val: Any, operator: str, value: Any) -> bool:
    if operator == "equals":
        return item_val == value
    elif operator == "contains":
        return value in str(item_val)
    elif operator == "gt":
        return float(item_val) > float(value)
    elif operator == "lt":
        return float(item_val) < float(value)
    return False
