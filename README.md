# Dare2Drive

A Discord trading-card game where players scavenge ship-part cards, assemble
them into a build, and race their ships through the sector. Built with
**discord.py**, **FastAPI**, **SQLAlchemy (async)**, **PostgreSQL**, and
**Redis**.

Each Discord server becomes a **System**, and any channel inside it can be
promoted to a playable **Sector** by a server admin — gameplay commands only
work in enabled sectors, while inventory and card state remain universe-wide.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/JordanGibbons/D2DBOT.git && cd D2DBOT

# 2. Install dev dependencies
pip install -e ".[dev]"

# 3. Run interactive setup (checks dependencies, provides install instructions)
d2d setup

# 4. Log in to Infisical
infisical login

# 5. Start everything (bot + api + postgres + redis)
d2d up
```

The entrypoint runs `alembic upgrade head` automatically on startup.

**Common development commands:**

```bash
d2d test              # Run tests
d2d lint --fix        # Lint and auto-fix
d2d format            # Format code
d2d check             # Run all quality checks
d2d hooks install     # Install pre-commit hooks
d2d --help            # See all commands
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full developer guide.

---

## Project Structure

```
dare2drive/
├── api/                  # FastAPI REST API
│   ├── main.py
│   └── routes/
│       ├── cards.py
│       ├── races.py
│       └── users.py
├── bot/                  # Discord bot
│   ├── main.py
│   ├── sector_gating.py  # Sector enforcement + command registry
│   └── cogs/
│       ├── admin.py      # /sector_*, /system_*, /admin_*
│       ├── cards.py      # /daily, /pack, /inventory, /inspect, /salvage
│       ├── hangar.py     # /start, /hangar, /equip, /build, /ship, /profile
│       ├── market.py     # /market, /list, /buy, /trade, /shop
│       ├── race.py       # /race, /multirace, /leaderboard, /wrecks
│       └── tutorial.py   # onboarding dialogue + step tracking
├── config/
│   ├── logging.py        # Unified logger
│   └── settings.py       # Pydantic BaseSettings
├── data/
│   ├── cards/            # Card definitions (JSON per slot)
│   │   ├── drives.json
│   │   ├── hulls.json
│   │   ├── overdrives.json
│   │   ├── reactors.json
│   │   ├── retros.json
│   │   ├── stabilizers.json
│   │   └── thrusters.json
│   ├── environments.json
│   ├── loot_tables.json
│   └── tutorial.json
├── db/
│   ├── models.py         # SQLAlchemy ORM models
│   ├── session.py        # Async engine + session factory
│   └── migrations/
│       ├── env.py
│       ├── script.py.mako
│       └── versions/
│           └── 0001_initial.py
├── docker/
│   ├── Dockerfile.dev
│   ├── Dockerfile.prod
│   └── entrypoint.sh
├── engine/
│   ├── card_mint.py      # Card rolling + serial number assignment
│   ├── class_engine.py   # Race-format classification from stats
│   ├── durability.py     # Part failure + wreck resolution
│   ├── environment.py    # Sector / space conditions
│   ├── race_engine.py    # Main race orchestrator
│   ├── ship_namer.py     # Ship Title name generation
│   └── stat_resolver.py  # Build stat aggregation
├── scripts/
│   ├── audit_pivot.py    # Guardrail against car-era vocab leaks
│   ├── dev.py            # `d2d` developer CLI
│   ├── generate_card_image.py
│   └── seed_cards.py
├── tests/
│   ├── conftest.py
│   ├── test_admin.py
│   ├── test_api.py
│   ├── test_audit_pivot.py
│   ├── test_card_mint.py
│   ├── test_card_renderer.py
│   ├── test_class_engine.py
│   ├── test_durability.py
│   ├── test_environment.py
│   ├── test_logging.py
│   ├── test_metrics.py
│   ├── test_models.py
│   ├── test_pack_reveal_view.py
│   ├── test_race_engine.py
│   ├── test_sector_gating.py
│   ├── test_seed_data.py
│   ├── test_settings.py
│   ├── test_ship_namer.py
│   ├── test_stat_resolver.py
│   └── test_systems_sectors.py
├── .env.example
├── .github/workflows/ci.yml
├── .gitignore
├── alembic.ini
├── docker-compose.prod.yml
├── docker-compose.yml
├── pyproject.toml
└── railway.toml
```

---

## Commands

### Discord Slash Commands

Gameplay commands only respond in channels enabled as **sectors** by a server
admin. Sector/system admin commands work anywhere in the guild.

#### Onboarding & inventory

| Command | Description |
|---------|-------------|
| `/start` | Create your profile and pick a hull class |
| `/skip_tutorial` | Skip the tutorial and jump straight into racing |
| `/daily` | Claim 100 Creds + one part for every slot (24h cooldown) |
| `/pack <type>` | Open a crate (`salvage_crate`, `gear_crate`, `legend_crate`) |
| `/inventory` | Browse your card collection (paginated) |
| `/inspect <card>` | View full stats for a card |
| `/request_inspect <user>` | Ask to peek inside another player's hangar |
| `/salvage <card>` | Scrap a part for Creds |

#### Ship building

| Command | Description |
|---------|-------------|
| `/hangar` | View your current build |
| `/equip <slot> <card>` | Equip a card to a build slot |
| `/autoequip <mode>` | Auto-equip your best or worst parts into every slot |
| `/build preview` | Preview your build's race format and stats |
| `/build mint` | Mint a Ship Title for your completed build |
| `/build disassemble` | Scrap your Ship Title and unlock the build |
| `/build new` | Open a new build slot (500 Creds) |
| `/build list` | List all your builds |
| `/ship rename <name>` | Set a custom name for your Ship Title |
| `/peek <user>` | View another player's hangar (public) |
| `/profile` | View your profile stats |

#### Racing

| Command | Description |
|---------|-------------|
| `/race <user>` | Challenge another player to a race |
| `/multirace` | Host a multi-player race event (2-min signup, max 3) |
| `/leaderboard` | View the top racers |
| `/wrecks` | View your wreck history |

#### Marketplace

| Command | Description |
|---------|-------------|
| `/market` | Browse market listings |
| `/list <card> <price>` | List a part for sale |
| `/buy <listing>` | Buy a part from the market |
| `/trade <user> <card>` | Initiate a card trade with another player |
| `/shop` | Browse the NPC parts shop (common parts always in stock) |
| `/shop_buy <part>` | Buy a common part from the NPC shop |

#### Server admin — sectors & systems

| Command                     | Description                                          |
| --------------------------- | ---------------------------------------------------- |
| `/sector_enable`            | Enable the current channel as a playable sector      |
| `/sector_disable`           | Disable the current channel                          |
| `/sector_rename <name>`     | Rename the current sector                            |
| `/system_info`              | Show this server's system status and active sectors  |
| `/system_set_flavor <text>` | (Owner) set flavor text for this system              |
| `/admin_set_sector_cap <n>` | (Bot owner) override the sector cap for a guild      |

---

## Database Migrations

```bash
# Create a new migration
infisical run --env=dev -- docker compose exec bot alembic revision --autogenerate -m "description"

# Apply migrations
infisical run --env=dev -- docker compose exec bot alembic upgrade head

# Rollback one step
infisical run --env=dev -- docker compose exec bot alembic downgrade -1
```

---

## Seeding Cards

```bash
infisical run --env=dev -- docker compose exec bot python -m scripts.seed_cards
```

This upserts all cards from `data/cards/*.json` into the database.

---

## Registering Discord Commands

Slash commands sync automatically on bot startup. To force a guild sync for
faster iteration during development, set `DEV_GUILD_ID` in your Infisical
secrets.

---

## Adding New Cards

1. Add the card JSON object to the appropriate file in `data/cards/`
2. Follow the existing stat schema for that slot type
3. Run the seed script to upsert into the database
4. Cards are immediately available in packs

### Card Rarities

| Rarity | Pack Weight | Special Properties |
|--------|-------------|--------------------|
| Common | High | Standard stats |
| Uncommon | Medium | Slightly better stats |
| Rare | Low | Notably better stats |
| Epic | Very Low | Strong stats + unique properties |
| Legendary | Extremely Low | Best stats, 50% wreck immunity |
| Ghost | Rarest | Immune to wrecks, shimmer effect |

---

## Generating Card Images

```bash
python -m scripts.generate_card_image --card-name "Rustbucket Reactor" --output cards_out/
```

Produces a 400×560 RGBA PNG with rarity-styled background, stat bars, and
print-number badge. Ghost cards get a shimmer overlay.

---

## Testing

```bash
# Run all tests with coverage
infisical run --env=dev -- docker compose exec bot pytest

# Run a specific test file
infisical run --env=dev -- docker compose exec bot pytest tests/test_race_engine.py -v

# Run locally (requires DATABASE_URL and REDIS_URL)
pytest --cov=bot --cov=engine --cov=api --cov=db --cov=config
```

Coverage threshold is set to **70%** in `pyproject.toml`.

---

## Production Deployment (Railway)

### Checklist

1. **Deploy Railway's Grafana Stack template** — [railway.com/deploy/8TLSQD](https://railway.com/deploy/8TLSQD)
   - This provisions: Grafana, Loki, Prometheus, Tempo (managed by Railway)
2. Push code to `main` branch and connect the GitHub repo to Railway
3. Railway detects `railway.toml` and deploys four services from this repo:
   - **bot** — `python -m bot.main`
   - **api** — `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - **ntfy-relay** — alert fan-out to ntfy.sh + Discord
   - **alertmanager** — evaluates Prometheus alert rules
4. Provision a **PostgreSQL** and **Redis** plugin in Railway
5. Set environment variables (see `.env.example`) on each service
6. Set `NTFY_RELAY_URL=http://ntfy-relay.railway.internal:9096` on the `alertmanager` service
7. Configure a **Railway Log Drain** (project settings → Log Drains):
   - Type: HTTP
   - URL: `http://<loki-service>.railway.internal:3100/loki/api/v1/push`
8. In the Railway Prometheus service config, point alertmanager at:
   `http://alertmanager.railway.internal:9093`

See [docs/adr/002-monitoring-stack.md](docs/adr/002-monitoring-stack.md) for the full architecture and connection details.

For a step-by-step guide on adding logs, metrics, and alerts to a new feature, see [docs/monitoring-guide.md](docs/monitoring-guide.md).

### Local prod smoke-test

```bash
docker compose -f docker-compose.prod.yml up --build
```

---

## Game Design Summary

### Race Flow

1. Both players' builds are aggregated into composite stats
2. A random space condition is rolled from `data/environments.json`
3. Environment weights modify stat importance
4. Durability checks run — parts can fail (minor/major/DNF)
5. Random variance (±5%) adds unpredictability
6. Final scores are computed, DNFs are sorted last
7. Winner gets XP + Creds, wreck results applied to losers

### Durability & Wrecks

- Each part has a durability stat (0–100)
- Lower durability = higher failure chance
- Overdrive parts push the reactor harder → higher overheat risk
- On failure: **minor** (score penalty), **major** (bigger penalty), **DNF** (race over)
- Wrecks can destroy 1–3 parts, weighted toward the failed slot
- **Ghost** cards are immune to wrecks
- **Legendary** cards have 50% wreck survival chance

### Economy

- `/daily` gives 100 Creds + one rolled part for every slot (24h cooldown)
- Crate prices: Salvage Crate (100), Gear Crate (350), Legend Crate (1200)
- Market allows player-to-player trading with price setting
- Race wins award XP and Creds

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Bot Framework | discord.py 2.x |
| REST API | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.x (async) |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Migrations | Alembic |
| Secrets | Infisical |
| Hosting | Railway |
| CI/CD | GitHub Actions |
| Images | Pillow |
| Config | Pydantic Settings |

---

## Development Commands

```bash
# Rebuild containers
docker compose up --build

# View logs
docker compose logs -f bot
docker compose logs -f api

# Enter bot container shell
docker compose exec bot bash

# Lint
ruff check .

# Format
black .

# Type check (if mypy installed)
mypy bot/ engine/ api/ db/ config/
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the git workflow, commit standards, and pre-commit setup.

---

## License
