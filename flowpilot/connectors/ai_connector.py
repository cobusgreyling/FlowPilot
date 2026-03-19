"""AI connector — LLM-powered data processing within workflows."""

from __future__ import annotations

import json
import os
from typing import Any

from flowpilot.connectors.base import BaseConnector


class AIConnector(BaseConnector):
    """AI processing connector using Claude or simulation fallback."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self._model = model

    @property
    def name(self) -> str:
        return "ai"

    def summarise(self, config: dict, context: dict) -> dict:
        """Summarise input data.

        Config:
            prompt: Additional instructions (optional)
            max_length: Target summary length in words (default 100)
        """
        prompt = config.get("prompt", "Summarise the following data concisely")
        data = _context_to_text(context)
        return self._call(f"{prompt}:\n\n{data}")

    def classify(self, config: dict, context: dict) -> dict:
        """Classify input data into categories.

        Config:
            categories: List of category names
            prompt: Additional instructions (optional)
        """
        categories = config.get("categories", ["positive", "negative", "neutral"])
        data = _context_to_text(context)
        prompt = (
            f"Classify the following into one of: {', '.join(categories)}.\n"
            f"Respond with only the category name.\n\n{data}"
        )
        return self._call(prompt)

    def extract(self, config: dict, context: dict) -> dict:
        """Extract structured information from text.

        Config:
            fields: List of field names to extract
            prompt: Additional instructions (optional)
        """
        fields = config.get("fields", ["key_points"])
        data = _context_to_text(context)
        prompt = (
            f"Extract the following fields from the text: {', '.join(fields)}.\n"
            f"Respond as JSON.\n\n{data}"
        )
        return self._call(prompt)

    def generate(self, config: dict, context: dict) -> dict:
        """Generate text based on a prompt and context.

        Config:
            prompt: Generation prompt with {{placeholders}} for context
        """
        prompt = config.get("prompt", "Generate a response based on the input")
        data = _context_to_text(context)
        return self._call(f"{prompt}\n\nContext:\n{data}")

    def _call(self, prompt: str) -> dict:
        """Call Claude or return simulated response."""
        try:
            from anthropic import Anthropic
            if os.environ.get("ANTHROPIC_API_KEY"):
                client = Anthropic()
                response = client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                return {
                    "status": "success",
                    "text": response.content[0].text,
                    "model": self._model,
                }
        except ImportError:
            pass

        return {
            "status": "simulated",
            "text": f"[AI would process: {prompt[:100]}...]",
            "message": "No anthropic SDK or ANTHROPIC_API_KEY — simulated",
        }


def _context_to_text(context: dict) -> str:
    parts = []
    for key, val in context.items():
        if isinstance(val, dict):
            text = val.get("text") or val.get("data") or val.get("message") or json.dumps(val)
            if not isinstance(text, str):
                text = json.dumps(text)
            parts.append(f"{key}: {text}")
        else:
            parts.append(f"{key}: {val}")
    return "\n".join(parts)
