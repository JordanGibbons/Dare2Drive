# ADR-002 — Monitoring Stack

**Status:** Accepted
**Date:** 2025-04
**Updated:** 2026-04
**Area:** tech

---

## Context

As Dare2Drive grows we need visibility into three things:

1. **Is the app up and working?** — health, latency, error rates.
2. **How is the game economy behaving?** — races run, packs opened, users registering, currency flows.
3. **What do the logs say when something breaks?** — structured, searchable logs.
4. **Can the team be notified in Discord when something goes wrong?**

The system runs on [Railway](https://railway.app) (two services: `bot` and `api`). Budget is close to zero, so every tool must either be free for the scale we're at or open-source and self-hostable.

---

## Decision

### Dev (local) — lightweight by default, metrics stack opt-in

Core services (`bot`, `api`, `db`, `redis`) start by default. A minimal metrics stack is
opt-in via Docker Compose profiles so developers aren't forced to run extra containers
just to work on game features:

```bash
d2d up                   # bot + api + db + redis only
d2d up --monitoring      # adds Prometheus + Grafana for local metric testing
```

| Layer | Tool | Why |
| --- | --- | --- |
| **App metrics** | `prometheus-fastapi-instrumentator` + custom `prometheus_client` counters in `api/metrics.py` | Zero-config HTTP metrics on `/metrics`; business counters (races, packs, etc.) callable from anywhere |
| **Metrics storage** | **Prometheus** `prom/prometheus:v2.52` | Industry standard; 30-day local retention |
| **Dashboards** | **Grafana** `grafana/grafana-oss:11.5.2` | Pre-provisioned Prometheus datasource baked into the image |

There is no local Loki or alerting. Log aggregation and alerts are production concerns handled
by Railway infrastructure.

### Production (Railway) — fully managed via the Grafana Stack submodule

All monitoring infrastructure is deployed from the `monitoring/railway` submodule
(`git@github.com:JordanGibbons/railway-grafana-stack.git`). Dashboards, alert rules, and the
Discord contact point are provisioned into the Grafana image at build time — no manual
configuration after deploy.

| Service | Deployed via | Notes |
| --- | --- | --- |
| **Grafana** | `monitoring/railway` submodule | Dashboards and alerting provisioned from `grafana/` |
| **Loki** | `monitoring/railway` submodule | Log storage |
| **Prometheus** | `monitoring/railway` submodule | Metrics storage + scrapes `dare2drive.railway.internal:8000` |
| **Tempo** | `monitoring/railway` submodule | Distributed tracing (optional) |
| **Log shipping** | Railway Log Drain → Loki | No sidecar needed |
| **Alert delivery** | Grafana unified alerting → Discord webhook | No Alertmanager or ntfy-relay |

### Alert routing

Grafana's built-in unified alerting handles everything — no separate Alertmanager process:

```text
Prometheus scrape ──▶ Grafana alert evaluation ──▶ Discord webhook (#alerts channel)
```

Alert rules: `monitoring/railway/grafana/alerting/rules.yml`
Contact point: `monitoring/railway/grafana/alerting/contact-points.yml`
Routing policy: `monitoring/railway/grafana/alerting/notification-policies.yml`

The `DISCORD_WEBHOOK_URL` env var is set on the Railway Grafana service.

### Structured JSON logging

`config/logging.py` emits one JSON object per line when `LOG_FORMAT=json`:

```json
{"ts": "2026-04-12T09:00:00Z", "level": "INFO", "logger": "bot.cogs.race", "msg": "Race completed"}
```

`LOG_FORMAT=json` is the default in production. Railway's Log Drain ships these directly to Loki
where fields (`level`, `logger`, `msg`) are parsed and searchable.

---

## Consequences

- `api/main.py` imports `prometheus-fastapi-instrumentator` (in `pyproject.toml`).
- `LOG_FORMAT=json` is set in `docker-compose.prod.yml`; `text` remains default for local dev.
- Dev: two monitoring services in `docker-compose.yml` (`prometheus`, `grafana`) behind the `monitoring` profile.
- Prod: zero monitoring services in this repo — everything runs from the `monitoring/railway` submodule.
- Env vars required on Railway Grafana service: `DISCORD_WEBHOOK_URL`, `LOKI_INTERNAL_URL`, `PROMETHEUS_INTERNAL_URL`, `TEMPO_INTERNAL_URL`.
- Local dev env vars: `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` (documented in `.env.example`).

---

## Getting Started (local dev)

```bash
# 1. Start the metrics stack (first run builds the Grafana image)
d2d up --monitoring --build

# 2. Open Grafana — Prometheus datasource is pre-configured
open http://localhost:3000   # admin / dare2drive

# 3. Open Prometheus for raw metric exploration
open http://localhost:9090
```

## Getting Started (production on Railway)

```bash
# 1. Deploy the monitoring/railway submodule to Railway
#    Each service (grafana, prometheus, loki, tempo) is a separate Railway service
#    built from its respective Dockerfile in the submodule

# 2. Set env vars on the Railway Grafana service:
#    DISCORD_WEBHOOK_URL   — Discord incoming webhook URL
#    LOKI_INTERNAL_URL     — http://<loki-service>.railway.internal:3100
#    PROMETHEUS_INTERNAL_URL — http://<prometheus-service>.railway.internal:9090
#    TEMPO_INTERNAL_URL    — http://<tempo-service>.railway.internal:3200

# 3. Configure Railway Log Drain (project settings → Log Drains):
#    Type: HTTP  URL: http://<loki-service>.railway.internal:3100/loki/api/v1/push
#    Services: api, bot

# 4. Verify in Grafana → Alerting → Alert rules that the three built-in rules
#    (API Down, High 5xx Error Rate, High P95 Latency) show as Normal
```
