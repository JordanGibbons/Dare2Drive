# ADR-002 — Monitoring Stack

**Status:** Accepted
**Date:** 2025-04
**Area:** tech

---

## Context

As Dare2Drive grows we need visibility into three things:

1. **Is the app up and working?** — health, latency, error rates.
2. **How is the game economy behaving?** — races run, packs opened, users registering, currency flows.
3. **What do the logs say when something breaks?** — structured, searchable logs.
4. **Can the team be paged to their phones and Discord when something goes wrong?**

The system runs on [Railway](https://railway.app) (two services: `bot` and `api`).  Budget is close to zero, so every tool must either be free for the scale we're at or open-source and self-hostable.

---

## Decision

Adopt the following open-source stack, deployed alongside the app in Docker Compose (dev) and as additional Railway services (prod):

| Layer | Tool | Why |
|---|---|---|
| **App metrics** | `prometheus-fastapi-instrumentator` + custom `prometheus_client` counters in `api/metrics.py` | Zero-config HTTP metrics on `/metrics`; business counters (races, packs, etc.) callable from anywhere |
| **Metrics storage & rules** | **Prometheus** `prom/prometheus:v2.52` | Industry standard; 30-day local retention; alerting rules live in-repo at `monitoring/prometheus/rules/` |
| **Log shipping** | **Fluent Bit** `fluent/fluent-bit:3.3` | Lightweight (~450 KB binary); Docker log-driver forward mode; JSON parsing for our structured logs |
| **Log storage** | **Grafana Loki** `grafana/loki:3.0` | Purpose-built for logs; native Grafana integration; no index = low storage cost |
| **Dashboards** | **Grafana** `grafana/grafana-oss:11.1` | Pre-provisioned dashboard (`monitoring/grafana/provisioning/`) auto-loads on first boot |
| **Alerting** | **Prometheus Alertmanager** + custom **ntfy-relay** | Alertmanager evaluates rules; ntfy-relay fans out to **both ntfy.sh and Discord** |
| **Phone alerts** | **[ntfy.sh](https://ntfy.sh)** (or self-hosted) | Free iOS/Android app; team subscribes to a private topic; no account required |
| **Discord alerts** | Discord incoming webhooks | Rich embeds with colours, fields, and error context posted to your team channels |

### Structured JSON logging

`config/logging.py` now supports `LOG_FORMAT=json` which emits one JSON object per line:

```json
{"ts": "2025-04-11T07:32:00+00:00", "level": "INFO", "logger": "bot.cogs.race", "msg": "Race completed"}
```

Set `LOG_FORMAT=json` in production so Fluent Bit can parse logs without extra regex rules.

### Alert fan-out flow

Both ntfy.sh (phone) and Discord webhook are handled by the `ntfy-relay` service.
Each is independently optional — leave the env var empty to disable that destination.

```
Prometheus ─── fires alert ──▶ Alertmanager ──▶ ntfy-relay:9096/alerts
                                                        │
                                         ┌──────────────┴──────────────┐
                                         ▼                             ▼
                                  POST ntfy.sh/{NTFY_TOPIC}   POST Discord webhook
                                         │                             │
                                 iOS/Android ntfy app       #alerts Discord channel
```

**Discord embed example (warning alert):**

```
⚠️  High HTTP 5xx error rate
Severity: WARNING   Status: FIRING
More than 5 % of API requests are returning 5xx errors over the last 5 minutes.
```

Critical alerts go to `DISCORD_WEBHOOK_URL_CRITICAL` if set, falling back to `DISCORD_WEBHOOK_URL`.

### Grafana Cloud alternative

If deploying Prometheus/Loki/Grafana on Railway turns out to be costly, migrate to **Grafana Cloud free tier** (10 k series, 50 GB logs, 14-day retention, 3 users) by:

- Pointing Fluent Bit's Loki output at the Grafana Cloud Loki endpoint.
- Adding a `remote_write` block to `prometheus.yml` pointing at the Grafana Cloud Prometheus endpoint.
- Deleting the `prometheus`, `loki`, and `grafana` services from `docker-compose.prod.yml`.

The alerting/ntfy/Discord path stays the same regardless.

---

## Consequences

- `api/main.py` now imports `prometheus-fastapi-instrumentator` (added to `pyproject.toml`).
- `LOG_FORMAT=json` is the new default for Docker environments; `text` remains default for local dev without `.env`.
- Six new monitoring services in `docker-compose.yml` (`fluent-bit`, `prometheus`, `loki`, `alertmanager`, `ntfy-relay`, `grafana`).
- New env vars: `NTFY_TOPIC`, `NTFY_URL`, `NTFY_TOKEN`, `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_CRITICAL`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` — all documented in `.env.example`.
- Business events (races, packs, wear) now emit Prometheus counters; adding new events is a one-liner.

---

## Getting Started

```bash
# 1. Copy and fill in the monitoring vars
cp .env.example .env

# Set NTFY_TOPIC to something private
# e.g. dare2drive-$(openssl rand -hex 8)

# Set DISCORD_WEBHOOK_URL to a Discord incoming webhook URL
# Channel Settings → Integrations → Webhooks → New Webhook → Copy URL

# 2. Start everything
docker compose up -d

# 3. Open Grafana
open http://localhost:3000   # admin / dare2drive (change in prod)

# 4. Install ntfy app → subscribe to your NTFY_TOPIC
# iOS: https://apps.apple.com/app/ntfy/id1625396347
# Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy
```
