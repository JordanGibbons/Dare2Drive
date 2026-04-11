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
4. **Can the team be paged to their phones and Discord when something goes wrong?**

The system runs on [Railway](https://railway.app) (two services: `bot` and `api`). Budget is close to zero, so every tool must either be free for the scale we're at or open-source and self-hostable.

---

## Decision

### Dev (local) — lightweight by default, monitoring opt-in

Core services (`bot`, `api`, `db`, `redis`) start by default. The monitoring stack is
opt-in via Docker Compose profiles so developers aren't forced to run six extra containers
just to work on game features:

```bash
d2d up                   # bot + api + db + redis only
d2d up --monitoring      # adds Grafana, Prometheus, Loki, Fluent Bit, Alertmanager, ntfy-relay
```

Monitoring services in `docker-compose.yml` carry `profiles: [monitoring]`:

| Layer | Tool | Why |
| --- | --- | --- |
| **App metrics** | `prometheus-fastapi-instrumentator` + custom `prometheus_client` counters in `api/metrics.py` | Zero-config HTTP metrics on `/metrics`; business counters (races, packs, etc.) callable from anywhere |
| **Metrics storage & rules** | **Prometheus** `prom/prometheus:v2.52` | Industry standard; 30-day local retention; alerting rules live in-repo at `monitoring/prometheus/rules/` |
| **Log shipping** | **Fluent Bit** `fluent/fluent-bit:4.2` | Lightweight; Docker log-driver forward mode; JSON parsing for structured logs |
| **Log storage** | **Grafana Loki** `grafana/loki:3.0` | Purpose-built for logs; native Grafana integration; low storage cost |
| **Dashboards** | **Grafana** `grafana/grafana-oss:11.1` | Pre-provisioned dashboard auto-loads on first boot |
| **Alerting** | **Prometheus Alertmanager** + custom **ntfy-relay** | Alertmanager evaluates rules; ntfy-relay fans out to ntfy.sh and Discord |

### Production (Railway) — hybrid managed + self-hosted

Grafana, Loki, and Prometheus are deployed via Railway's one-click **Grafana Stack template**
(`https://railway.com/deploy/8TLSQD`). This gives persistent volumes and independent restarts
at no extra maintenance cost. Alertmanager and ntfy-relay are deployed from this repo as
Railway services.

| Service | How deployed | Notes |
| --- | --- | --- |
| **Grafana** | Railway Grafana Stack template | Dashboard UI |
| **Loki** | Railway Grafana Stack template | Log storage |
| **Prometheus** | Railway Grafana Stack template | Metrics storage + scraping |
| **Alertmanager** | This repo (`monitoring/alertmanager/`) | Custom rules + routing |
| **ntfy-relay** | This repo (`monitoring/ntfy-relay/`) | Discord + ntfy fan-out |
| **Log shipping** | Railway Log Drain → Loki | No Fluent Bit needed in prod |

#### Connecting the pieces on Railway

1. **Prometheus → Alertmanager**: In the Railway Prometheus service, set the alertmanager URL to the internal address of the `alertmanager` service (e.g. `http://alertmanager.railway.internal:9093`). Upload your custom `monitoring/prometheus/rules/` via a Railway volume or mount.

2. **Alertmanager → ntfy-relay**: Set `NTFY_RELAY_URL=http://ntfy-relay.railway.internal:9096` on the `alertmanager` Railway service. The entrypoint script substitutes this into the config at startup.

3. **Log drain → Loki**: In Railway's project settings → Log Drains, add an HTTP drain pointing at your Railway Loki push endpoint: `http://<loki-service>.railway.internal:3100/loki/api/v1/push`.

---

### Structured JSON logging

`config/logging.py` supports `LOG_FORMAT=json` which emits one JSON object per line:

```json
{"ts": "2025-04-11T07:32:00+00:00", "level": "INFO", "logger": "bot.cogs.race", "msg": "Race completed"}
```

Set `LOG_FORMAT=json` in production. Railway's log drain ships these directly to Loki.

### Alert fan-out flow

```text
Prometheus ─── fires alert ──▶ Alertmanager ──▶ ntfy-relay:9096/alerts
                                                        │
                                         ┌──────────────┴──────────────┐
                                         ▼                             ▼
                                  POST ntfy.sh/{NTFY_TOPIC}   POST Discord webhook
                                         │                             │
                                 iOS/Android ntfy app       #alerts Discord channel
```

Critical alerts go to `DISCORD_WEBHOOK_URL_CRITICAL` if set, falling back to `DISCORD_WEBHOOK_URL`.

---

## Consequences

- `api/main.py` imports `prometheus-fastapi-instrumentator` (in `pyproject.toml`).
- `LOG_FORMAT=json` is the production default; `text` remains default for local dev.
- Dev: six monitoring services in `docker-compose.yml` (`fluent-bit`, `prometheus`, `loki`, `alertmanager`, `ntfy-relay`, `grafana`).
- Prod: two monitoring services in this repo (`alertmanager`, `ntfy-relay`); the rest via Railway template.
- New env vars: `NTFY_TOPIC`, `NTFY_URL`, `NTFY_TOKEN`, `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_CRITICAL`, `NTFY_RELAY_URL`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` — documented in `.env.example`.

---

## Getting Started (local dev)

```bash
# 1. Copy and fill in monitoring vars
cp .env.example .env

# Set NTFY_TOPIC to something private
# e.g. dare2drive-$(openssl rand -hex 8)

# Set DISCORD_WEBHOOK_URL to a Discord incoming webhook URL
# Channel Settings → Integrations → Webhooks → New Webhook → Copy URL

# 2. Start everything (includes full monitoring stack)
d2d up

# 3. Open Grafana
open http://localhost:3000   # admin / dare2drive (change in prod)

# 4. Install ntfy app → subscribe to your NTFY_TOPIC
# iOS: https://apps.apple.com/app/ntfy/id1625396347
# Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy
```

## Getting Started (production on Railway)

```bash
# 1. Deploy the Grafana Stack template
#    https://railway.com/deploy/8TLSQD
#    This creates: grafana, loki, prometheus, tempo services

# 2. Push this repo to Railway — railway.toml deploys:
#    bot, api, ntfy-relay, alertmanager

# 3. Set env vars on the alertmanager Railway service:
#    NTFY_RELAY_URL=http://ntfy-relay.railway.internal:9096

# 4. Set env vars on the ntfy-relay Railway service:
#    NTFY_TOPIC, NTFY_URL, NTFY_TOKEN, DISCORD_WEBHOOK_URL, DISCORD_WEBHOOK_URL_CRITICAL

# 5. Configure Railway Log Drain (project settings → Log Drains):
#    Type: HTTP  URL: http://<loki>.railway.internal:3100/loki/api/v1/push

# 6. In the Railway Prometheus service, configure alertmanager_url:
#    http://alertmanager.railway.internal:9093
```
