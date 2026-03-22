"""Embeddable workflow trigger widget.

Generates self-contained HTML widgets that can be embedded in external
applications to trigger FlowPilot workflows via a simple form.
"""

from __future__ import annotations

import html
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

_WIDGETS: dict[str, "WidgetConfig"] = {}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WidgetField:
    name: str
    label: str
    field_type: str = "text"  # text | email | number | select | textarea
    required: bool = False
    options: list[str] = field(default_factory=list)
    placeholder: str = ""


@dataclass
class WidgetConfig:
    workflow_id: str
    title: str = "Run Workflow"
    description: str = ""
    input_fields: list[WidgetField] = field(default_factory=list)
    theme: str = "light"  # light | dark
    button_text: str = "Submit"
    callback_url: str = ""
    api_key: str = ""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#ffffff;--fg:#1a1a2e;--card:#ffffff;--border:#e0e0e0;
--accent:#4361ee;--accent-hover:#3a56d4;--input-bg:#f8f9fa;
--success:#2ecc71;--error:#e74c3c;--shadow:0 4px 24px rgba(0,0,0,.08)}
.dark{--bg:#1a1a2e;--fg:#e8e8f0;--card:#26264a;--border:#3d3d6b;
--accent:#6c83f7;--accent-hover:#5a73e8;--input-bg:#2e2e54;
--success:#2ecc71;--error:#e74c3c;--shadow:0 4px 24px rgba(0,0,0,.3)}
body,.fp-widget{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
.fp-widget{max-width:480px;margin:24px auto;background:var(--card);
border:1px solid var(--border);border-radius:12px;padding:28px 32px;
box-shadow:var(--shadow)}
.fp-widget h2{font-size:1.25rem;margin-bottom:4px}
.fp-widget .desc{font-size:.875rem;opacity:.7;margin-bottom:20px}
.fp-widget label{display:block;font-size:.8125rem;font-weight:600;
margin-bottom:4px;margin-top:14px}
.fp-widget input,.fp-widget select,.fp-widget textarea{width:100%;
padding:10px 12px;border:1px solid var(--border);border-radius:8px;
font-size:.875rem;background:var(--input-bg);color:var(--fg);
transition:border .2s}
.fp-widget input:focus,.fp-widget select:focus,.fp-widget textarea:focus{
outline:none;border-color:var(--accent)}
.fp-widget textarea{resize:vertical;min-height:72px}
.fp-widget button{width:100%;margin-top:22px;padding:12px;border:none;
border-radius:8px;background:var(--accent);color:#fff;font-size:.9375rem;
font-weight:600;cursor:pointer;transition:background .2s}
.fp-widget button:hover{background:var(--accent-hover)}
.fp-widget button:disabled{opacity:.6;cursor:not-allowed}
.fp-msg{margin-top:12px;padding:10px 14px;border-radius:8px;font-size:.8125rem;
display:none}
.fp-msg.ok{display:block;background:var(--success);color:#fff}
.fp-msg.err{display:block;background:var(--error);color:#fff}
@media(max-width:520px){.fp-widget{margin:12px;padding:20px 18px}}
"""

# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------

_JS = """
function fpSubmit(e,cfg){
  e.preventDefault();
  var btn=e.target.querySelector('button');
  var msg=document.getElementById('fp-msg-'+cfg.wid);
  btn.disabled=true;btn.textContent='Sending...';
  msg.className='fp-msg';msg.style.display='none';
  var fd=new FormData(e.target);var body={};
  fd.forEach(function(v,k){body[k]=v});
  body._workflow_id=cfg.workflow_id;
  var headers={'Content-Type':'application/json'};
  if(cfg.api_key) headers['Authorization']='Bearer '+cfg.api_key;
  fetch(cfg.callback_url,{method:'POST',headers:headers,
    body:JSON.stringify(body)})
  .then(function(r){if(!r.ok)throw new Error(r.statusText);return r.json()})
  .then(function(){msg.className='fp-msg ok';
    msg.textContent='Workflow triggered successfully!';msg.style.display='block'})
  .catch(function(err){msg.className='fp-msg err';
    msg.textContent='Error: '+err.message;msg.style.display='block'})
  .finally(function(){btn.disabled=false;btn.textContent=cfg.btn_text});
}
"""


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class WidgetGenerator:
    """Generate embeddable HTML widgets for triggering workflows."""

    def _render_field(self, f: WidgetField) -> str:
        esc = html.escape
        req = " required" if f.required else ""
        ph = f' placeholder="{esc(f.placeholder)}"' if f.placeholder else ""
        lbl = f'<label for="{esc(f.name)}">{esc(f.label)}</label>'
        if f.field_type == "textarea":
            inp = f'<textarea id="{esc(f.name)}" name="{esc(f.name)}"{req}{ph}></textarea>'
        elif f.field_type == "select":
            opts = "".join(f'<option value="{esc(o)}">{esc(o)}</option>' for o in f.options)
            inp = f'<select id="{esc(f.name)}" name="{esc(f.name)}"{req}>{opts}</select>'
        else:
            inp = (
                f'<input type="{esc(f.field_type)}" id="{esc(f.name)}" '
                f'name="{esc(f.name)}"{req}{ph}/>'
            )
        return lbl + inp

    def generate_html(self, config: WidgetConfig) -> str:
        """Generate a standalone HTML snippet with embedded CSS and JS."""
        wid = uuid.uuid4().hex[:8]
        fields_html = "\n".join(self._render_field(f) for f in config.input_fields)
        theme_cls = " dark" if config.theme == "dark" else ""
        cfg_json = json.dumps(
            {
                "wid": wid,
                "workflow_id": config.workflow_id,
                "callback_url": config.callback_url,
                "api_key": config.api_key,
                "btn_text": config.button_text,
            }
        )
        desc = (
            f'<p class="desc">{html.escape(config.description)}</p>'
            if config.description
            else ""
        )
        return (
            f"<style>{_CSS}</style>\n"
            f'<div class="fp-widget{theme_cls}">\n'
            f"<h2>{html.escape(config.title)}</h2>\n"
            f"{desc}\n"
            f'<form onsubmit="fpSubmit(event,{cfg_json});return false">\n'
            f"{fields_html}\n"
            f"<button type=\"submit\">{html.escape(config.button_text)}</button>\n"
            f'<div id="fp-msg-{wid}" class="fp-msg"></div>\n'
            f"</form>\n</div>\n"
            f"<script>{_JS}</script>"
        )

    def generate_iframe_snippet(self, config: WidgetConfig, host: str) -> str:
        """Return an iframe embed code pointing at the hosted widget."""
        url = f"{host.rstrip('/')}/widgets/{config.workflow_id}"
        return (
            f'<iframe src="{html.escape(url)}" '
            f'style="border:none;width:100%;max-width:520px;min-height:400px" '
            f'title="{html.escape(config.title)}"></iframe>'
        )

    def generate_script_snippet(self, config: WidgetConfig, host: str) -> str:
        """Return a script-tag embed code."""
        url = f"{host.rstrip('/')}/widgets/{config.workflow_id}/embed.js"
        return f'<script src="{html.escape(url)}" async></script>'

    def create_widget_endpoint(self, config: WidgetConfig) -> Any:
        """Register a FastAPI route that serves the widget HTML."""
        if not HAS_FASTAPI:
            raise ImportError("FastAPI is required: pip install fastapi")
        _WIDGETS[config.workflow_id] = config
        page = self.preview_widget(config)

        app_router: dict[str, Any] = {}

        async def widget_page(request: Request) -> HTMLResponse:  # noqa: ARG001
            return HTMLResponse(content=page)

        app_router["path"] = f"/widgets/{config.workflow_id}"
        app_router["endpoint"] = widget_page
        app_router["methods"] = ["GET"]
        return app_router

    def list_widgets(self) -> list[dict[str, str]]:
        """Return a list of registered widget summaries."""
        return [
            {"workflow_id": wid, "title": cfg.title}
            for wid, cfg in _WIDGETS.items()
        ]

    def preview_widget(self, config: WidgetConfig) -> str:
        """Return a full HTML page for previewing the widget."""
        widget_html = self.generate_html(config)
        theme_bg = "#1a1a2e" if config.theme == "dark" else "#f4f5f7"
        return (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            '<meta charset="utf-8"/>\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
            f"<title>{html.escape(config.title)}</title>\n"
            f"<style>body{{background:{theme_bg};padding:40px 0}}</style>\n"
            f"</head>\n<body>\n{widget_html}\n</body>\n</html>"
        )
