"""Multi-model planner supporting Claude, OpenAI, Gemini, and Ollama."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .planner import PLANNER_SYSTEM_PROMPT
from .engine import WorkflowGraph

logger = logging.getLogger(__name__)


class PlannerBackend(Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


@dataclass
class PlannerConfig:
    backend: PlannerBackend
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096

    def __post_init__(self):
        defaults = {
            PlannerBackend.CLAUDE: ("claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
            PlannerBackend.OPENAI: ("gpt-4o-mini", "OPENAI_API_KEY"),
            PlannerBackend.GEMINI: ("gemini-2.0-flash", "GOOGLE_API_KEY"),
            PlannerBackend.OLLAMA: ("llama3.2", ""),
        }
        default_model, env_key = defaults.get(self.backend, ("", ""))
        if not self.model_name:
            self.model_name = default_model
        if not self.api_key and env_key:
            self.api_key = os.environ.get(env_key, "")
        if self.backend == PlannerBackend.OLLAMA and not self.base_url:
            self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


class MultiPlanner:
    """Workflow planner with multiple LLM backend support and fallback chain."""

    def __init__(self, configs: list[PlannerConfig] = None, fallback_order: list[PlannerBackend] = None):
        self._configs: dict[PlannerBackend, PlannerConfig] = {}
        if configs:
            for c in configs:
                self._configs[c.backend] = c
        self._fallback_order = fallback_order or [
            PlannerBackend.CLAUDE, PlannerBackend.OPENAI,
            PlannerBackend.GEMINI, PlannerBackend.OLLAMA,
        ]

    def plan(self, description: str) -> dict:
        errors = []
        for backend in self._fallback_order:
            config = self._configs.get(backend)
            if not config:
                continue
            try:
                logger.info(f"Trying {backend.value} planner ({config.model_name})")
                return self._dispatch(backend, description, config)
            except Exception as e:
                logger.warning(f"{backend.value} failed: {e}")
                errors.append(f"{backend.value}: {e}")
        raise RuntimeError(f"All planner backends failed: {'; '.join(errors)}")

    def _dispatch(self, backend: PlannerBackend, description: str, config: PlannerConfig) -> dict:
        handlers = {
            PlannerBackend.CLAUDE: self._plan_claude,
            PlannerBackend.OPENAI: self._plan_openai,
            PlannerBackend.GEMINI: self._plan_gemini,
            PlannerBackend.OLLAMA: self._plan_ollama,
        }
        return handlers[backend](description, config)

    def _plan_claude(self, description: str, config: PlannerConfig) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key)
        response = client.messages.create(
            model=config.model_name,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": description}],
        )
        return self._parse_response(response.content[0].text)

    def _plan_openai(self, description: str, config: PlannerConfig) -> dict:
        import openai
        kwargs = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = openai.OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": description},
            ],
        )
        return self._parse_response(response.choices[0].message.content)

    def _plan_gemini(self, description: str, config: PlannerConfig) -> dict:
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        model = genai.GenerativeModel(
            config.model_name,
            system_instruction=PLANNER_SYSTEM_PROMPT,
        )
        response = model.generate_content(
            description,
            generation_config=genai.types.GenerationConfig(
                temperature=config.temperature,
                max_output_tokens=config.max_tokens,
            ),
        )
        return self._parse_response(response.text)

    def _plan_ollama(self, description: str, config: PlannerConfig) -> dict:
        import requests
        response = requests.post(
            f"{config.base_url}/api/generate",
            json={
                "model": config.model_name,
                "system": PLANNER_SYSTEM_PROMPT,
                "prompt": description,
                "stream": False,
                "options": {"temperature": config.temperature, "num_predict": config.max_tokens},
            },
            timeout=120,
        )
        response.raise_for_status()
        return self._parse_response(response.json()["response"])

    @staticmethod
    def _parse_response(text: str) -> dict:
        # Try to extract JSON from markdown code blocks
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1)
        text = text.strip()
        return json.loads(text)

    def list_backends(self) -> list[dict]:
        results = []
        for backend in PlannerBackend:
            config = self._configs.get(backend)
            results.append({
                "backend": backend.value,
                "configured": config is not None,
                "model": config.model_name if config else None,
                "sdk_available": self._check_sdk(backend),
            })
        return results

    def test_backend(self, backend: PlannerBackend) -> dict:
        config = self._configs.get(backend)
        if not config:
            return {"backend": backend.value, "status": "not configured"}
        try:
            result = self._dispatch(backend, "Send a Slack message saying hello", config)
            return {"backend": backend.value, "status": "ok", "nodes": len(result.get("nodes", []))}
        except Exception as e:
            return {"backend": backend.value, "status": "error", "error": str(e)}

    @staticmethod
    def _check_sdk(backend: PlannerBackend) -> bool:
        try:
            if backend == PlannerBackend.CLAUDE:
                import anthropic
            elif backend == PlannerBackend.OPENAI:
                import openai
            elif backend == PlannerBackend.GEMINI:
                import google.generativeai
            elif backend == PlannerBackend.OLLAMA:
                import requests
            return True
        except ImportError:
            return False
