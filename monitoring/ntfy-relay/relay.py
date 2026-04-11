"""Minimal relay: Alertmanager webhook → ntfy.sh push notification.

Listens on port 9096.  Alertmanager POSTs its JSON payload here; this relay
translates it into an ntfy.sh HTTP POST so the team receives phone alerts.

Environment variables:
  NTFY_URL    Base URL of the ntfy server (default: https://ntfy.sh)
  NTFY_TOPIC  Topic name — team members subscribe to this in the ntfy app
  NTFY_TOKEN  Optional Bearer token for a self-hosted ntfy instance
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

app = FastAPI(title="ntfy-relay", docs_url=None, redoc_url=None)

NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "dare2drive-alerts")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

_SEVERITY_PRIORITY = {
    "critical": "urgent",
    "warning": "high",
    "info": "default",
}

_SEVERITY_TAGS = {
    "critical": ["rotating_light", "dare2drive"],
    "warning": ["warning", "dare2drive"],
    "info": ["information_source", "dare2drive"],
}


@app.post("/ntfy")
async def relay(request: Request) -> JSONResponse:
    """Receive an Alertmanager webhook and forward each alert to ntfy.sh."""
    body: dict[str, Any] = await request.json()
    alerts: list[dict] = body.get("alerts", [])
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for alert in alerts:
            labels: dict = alert.get("labels", {})
            annotations: dict = alert.get("annotations", {})
            status: str = alert.get("status", "firing")
            severity: str = labels.get("severity", "warning")

            title = annotations.get("summary", labels.get("alertname", "Dare2Drive Alert"))
            message = annotations.get("description", "No description.")

            if status == "resolved":
                title = f"✅ RESOLVED: {title}"
                priority = "default"
                tags = ["white_check_mark", "dare2drive"]
            else:
                title = f"🚨 {title}"
                priority = _SEVERITY_PRIORITY.get(severity, "default")
                tags = _SEVERITY_TAGS.get(severity, ["dare2drive"])

            headers: dict[str, str] = {
                "Title": title,
                "Priority": priority,
                "Tags": ",".join(tags),
                "Content-Type": "text/plain",
            }
            if NTFY_TOKEN:
                headers["Authorization"] = f"Bearer {NTFY_TOKEN}"

            try:
                resp = await client.post(
                    f"{NTFY_URL}/{NTFY_TOPIC}",
                    content=message.encode(),
                    headers=headers,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # Log the full error server-side; return a generic message to callers
                # to avoid leaking internal details (stack traces, URLs with tokens).
                log.error("ntfy forward failed: %s", exc)
                errors.append("ntfy delivery failed — check relay logs")

    if errors:
        return JSONResponse({"status": "partial_error", "errors": errors}, status_code=207)
    return JSONResponse({"status": "ok", "forwarded": len(alerts)})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
