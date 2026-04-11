# Dare2Drive

A Discord trading-card game where players collect car-part cards, assemble them
into a build, and race against other players. Built with **discord.py**,
**FastAPI**, **SQLAlchemy (async)**, **PostgreSQL**, and **Redis**.

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
│   └── cogs/
│       ├── cards.py      # /daily, /pack, /inventory, /inspect
│       ├── garage.py     # /start, /garage, /equip, /profile
│       ├── market.py     # /market, /list, /buy, /trade
│       └── race.py       # /race, /challenge, /leaderboard, /wrecks
├── config/
│   ├── logging.py        # Unified logger
│   └── settings.py       # Pydantic BaseSettings
├── data/
│   ├── cards/            # Card definitions (JSON per slot)
│   │   ├── brakes.json
│   │   ├── chassis.json
│   │   ├── engines.json
│   │   ├── suspension.json
│   │   ├── tires.json
│   │   ├── transmissions.json
│   │   └── turbos.json
│   ├── environments.json
│   └── loot_tables.json
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
│   ├── durability.py     # Part failure + wreck resolution
│   ├── environment.py    # Track conditions
│   ├── race_engine.py    # Main race orchestrator
│   └── stat_resolver.py  # Build stat aggregation
├── scripts/
│   ├── generate_card_image.py
│   └── seed_cards.py
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_card_renderer.py
│   ├── test_durability.py
│   ├── test_environment.py
│   ├── test_logging.py
│   ├── test_models.py
│   ├── test_race_engine.py
│   ├── test_seed_data.py
│   ├── test_settings.py
│   └── test_stat_resolver.py
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

| Command | Description |
|---------|-------------|
| `/start` | Create your profile and choose a body type |
| `/daily` | Claim daily credits + chance at a free card |
| `/pack <type>` | Open a card pack (`junkyard_pack`, `performance_pack`, `legend_crate`) |
| `/inventory` | Browse your card collection (paginated) |
| `/inspect <card>` | View full stats for a card |
| `/garage` | View your current build |
| `/equip <card>` | Equip a card to your build |
| `/profile` | View your profile stats |
| `/race` | Race against a random opponent |
| `/challenge <user>` | Challenge another player to a race |
| `/leaderboard` | View the top racers |
| `/wrecks` | View your wreck history |
| `/market` | Browse market listings |
| `/list <card> <price>` | List a card for sale |
| `/buy <listing>` | Purchase a market listing |
| `/trade <user> <card>` | Offer a card trade |

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
python -m scripts.generate_card_image --card-name "V8 Rumbler" --output cards_out/
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

1. Push code to `main` branch
2. Connect GitHub repo to Railway
3. Add all environment variables from `.env.example` to Railway
4. Railway will detect `railway.toml` and deploy two services:
   - **bot** — runs `python -m bot.main`
   - **api** — runs `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
5. Provision a PostgreSQL and Redis addon in Railway
6. Ensure `DATABASE_URL` and `REDIS_URL` are set in Railway environment

### Production Docker

```bash
docker compose -f docker-compose.prod.yml up --build
```

---

## Game Design Summary

### Race Flow

1. Both players' builds are aggregated into composite stats
2. A random environment (track condition) is rolled
3. Environment weights modify stat importance
4. Durability checks run — parts can fail (minor/major/DNF)
5. Random variance (±5%) adds unpredictability
6. Final scores are computed, DNFs are sorted last
7. Winner gets XP + credits, wreck results applied to losers

### Durability & Wrecks

- Each part has a durability stat (0–100)
- Lower durability = higher failure chance
- Turbo parts increase engine temperature → higher overheat risk
- On failure: **minor** (score penalty), **major** (bigger penalty), **DNF** (race over)
- Wrecks can destroy 1–3 parts, weighted toward the failed slot
- **Ghost** cards are immune to wrecks
- **Legendary** cards have 50% wreck survival chance

### Economy

- `/daily` gives 50–150 credits + 20% chance at a common card
- Pack prices: Junkyard (100), Performance (300), Legend Crate (800)
- Market allows player-to-player trading with price setting
- Race wins award XP and credits

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
