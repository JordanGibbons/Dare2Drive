"""Alert relay: Alertmanager webhook → ntfy.sh (phone) + Discord webhook.

Listens on port 9096.  A single ``POST /alerts`` endpoint fans out to both
ntfy.sh and a Discord webhook channel simultaneously, so the team gets phone
push notifications *and* rich Discord embeds in one shot.

Each destination is optional — omit the relevant env var to skip it:

Environment variables:
  NTFY_URL              Base URL of the ntfy server (default: https://ntfy.sh)
  NTFY_TOPIC            Topic name — team members subscribe in the ntfy app.
                        Leave empty to disable ntfy delivery.
  NTFY_TOKEN            Optional Bearer token for a self-hosted ntfy instance.

  DISCORD_WEBHOOK_URL   Discord incoming webhook URL for general alerts.
                        Leave empty to disable Discord delivery.
  DISCORD_WEBHOOK_URL_CRITICAL
                        Optional separate Discord channel for critical alerts.
                        Falls back to DISCORD_WEBHOOK_URL if not set.
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

# ntfy config
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

# Discord config
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_URL_CRITICAL = os.environ.get("DISCORD_WEBHOOK_URL_CRITICAL", "")

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

# Discord embed colours keyed by severity
_DISCORD_COLOURS = {
    "critical": 0xED4245,  # red
    "warning": 0xFEE75C,  # yellow
    "info": 0x57F287,  # green
}
_DISCORD_COLOUR_RESOLVED = 0x57F287  # green


def _build_discord_embed(alert: dict) -> dict:
    """Build a Discord embed dict from a single Alertmanager alert payload."""
    labels: dict = alert.get("labels", {})
    annotations: dict = alert.get("annotations", {})
    status: str = alert.get("status", "firing")
    severity: str = labels.get("severity", "warning")
    alert_name: str = labels.get("alertname", "Alert")

    summary = annotations.get("summary", alert_name)
    description = annotations.get("description", "No additional details.")
    generator_url: str = alert.get("generatorURL", "")

    if status == "resolved":
        title = f"✅ RESOLVED — {summary}"
        colour = _DISCORD_COLOUR_RESOLVED
    else:
        emoji = "🚨" if severity == "critical" else "⚠️"
        title = f"{emoji} {summary}"
        colour = _DISCORD_COLOURS.get(severity, _DISCORD_COLOURS["warning"])

    fields = [
        {"name": "Severity", "value": severity.upper(), "inline": True},
        {"name": "Status", "value": status.upper(), "inline": True},
    ]

    # Include any extra labels as fields (skip standard ones)
    skip_labels = {"alertname", "severity"}
    for key, value in sorted(labels.items()):
        if key not in skip_labels:
            fields.append({"name": key.replace("_", " ").title(), "value": value, "inline": True})

    embed: dict = {
        "title": title,
        "description": description,
        "color": colour,
        "fields": fields,
    }
    if generator_url:
        embed["url"] = generator_url

    return embed


async def _send_ntfy(client: httpx.AsyncClient, alert: dict) -> str | None:
    """Forward one alert to ntfy.sh.  Returns an error string on failure."""
    if not NTFY_TOPIC:
        return None

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
        log.error("ntfy forward failed: %s", exc)
        return "ntfy delivery failed — check relay logs"
    return None


async def _send_discord(client: httpx.AsyncClient, alert: dict) -> str | None:
    """Forward one alert to the Discord webhook.  Returns an error string on failure."""
    severity: str = alert.get("labels", {}).get("severity", "warning")
    status: str = alert.get("status", "firing")

    # Use the critical channel when configured and the alert is critical + firing.
    if DISCORD_WEBHOOK_URL_CRITICAL and severity == "critical" and status != "resolved":
        webhook_url = DISCORD_WEBHOOK_URL_CRITICAL
    elif DISCORD_WEBHOOK_URL:
        webhook_url = DISCORD_WEBHOOK_URL
    else:
        return None  # Discord delivery disabled

    embed = _build_discord_embed(alert)
    payload = {"embeds": [embed]}

    try:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Discord webhook forward failed: %s", exc)
        return "Discord delivery failed — check relay logs"
    return None


@app.post("/alerts")
async def relay_alerts(request: Request) -> JSONResponse:
    """Receive an Alertmanager webhook and fan out to ntfy + Discord."""
    body: dict[str, Any] = await request.json()
    alerts: list[dict] = body.get("alerts", [])
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for alert in alerts:
            for err in [
                await _send_ntfy(client, alert),
                await _send_discord(client, alert),
            ]:
                if err:
                    errors.append(err)

    if errors:
        return JSONResponse({"status": "partial_error", "errors": errors}, status_code=207)
    return JSONResponse({"status": "ok", "forwarded": len(alerts)})


# ---------------------------------------------------------------------------
# Legacy endpoint kept for backwards compatibility
# ---------------------------------------------------------------------------


@app.post("/ntfy")
async def relay_ntfy_only(request: Request) -> JSONResponse:
    """Receive an Alertmanager webhook and forward to ntfy only (legacy path)."""
    body: dict[str, Any] = await request.json()
    alerts: list[dict] = body.get("alerts", [])
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for alert in alerts:
            err = await _send_ntfy(client, alert)
            if err:
                errors.append(err)

    if errors:
        return JSONResponse({"status": "partial_error", "errors": errors}, status_code=207)
    return JSONResponse({"status": "ok", "forwarded": len(alerts)})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
