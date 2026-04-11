# Contributing to Dare2Drive

This document covers the git workflow, commit standards, and tooling every contributor should know before opening a pull request.

---

## Table of Contents

- [Contributing to Dare2Drive](#contributing-to-dare2drive)
  - [Table of Contents](#table-of-contents)
  - [Developer CLI](#developer-cli)
  - [First-Time Setup](#first-time-setup)
  - [Branch Strategy](#branch-strategy)
  - [Commit Messages](#commit-messages)
    - [Allowed types](#allowed-types)
    - [Examples](#examples)
    - [Using Commitizen (optional but recommended)](#using-commitizen-optional-but-recommended)
  - [Pre-commit Hooks](#pre-commit-hooks)
    - [What runs](#what-runs)
    - [Running hooks manually](#running-hooks-manually)
    - [If a hook auto-fixes your files](#if-a-hook-auto-fixes-your-files)
    - [Skipping hooks (emergencies only)](#skipping-hooks-emergencies-only)
  - [Pull Requests](#pull-requests)
    - [PR title](#pr-title)
  - [CI / GitHub Actions](#ci--github-actions)
  - [Branch Protection](#branch-protection)

---

## Developer CLI

Dare2Drive includes a `d2d` CLI tool to streamline common development tasks. After installing dev dependencies, you can use it for everything from setup to testing to docker management.

**Quick reference:**

```bash
# Interactive setup guide (check dependencies, installation help)
d2d setup

# Testing
d2d test              # Run all tests with coverage
d2d test --no-cov     # Run tests without coverage
d2d test path/to/test # Run specific test file

# Code quality
d2d lint              # Check code with ruff
d2d lint --fix        # Auto-fix issues
d2d format            # Format code with black
d2d format --check    # Check formatting without changes
d2d check             # Run all checks (lint + format + test)

# Pre-commit hooks
d2d hooks install     # Install hooks
d2d hooks run         # Run hooks on staged files
d2d hooks run --all   # Run hooks on all files
d2d hooks update      # Update hook versions

# Docker & Services
d2d up                # Start services (bot, api, postgres, redis)
d2d up -b             # Start and rebuild containers
d2d up -d             # Start in background (detached)
d2d down              # Stop services
d2d down -v           # Stop and remove volumes
d2d logs              # View service logs
d2d shell <service>   # Open shell in container (bot/api/postgres/redis)

# Database
d2d migrate           # Run migrations to latest
d2d makemigration -m "message"  # Create new migration
d2d seed              # Seed database with card data
d2d db                # Open PostgreSQL shell

# Docker builds
d2d build             # Build dev image
d2d build --prod      # Build production image

# Git & GitHub
d2d commit            # Interactive commit (commitizen)
d2d commit -a         # Stage all changes and commit
d2d commit -ap        # Stage, commit, and push
d2d commit -t feat -m "add feature"  # Quick commit
d2d pr                # Create PR to demo branch (auto-fills from commits)
d2d pr --web          # Open PR creation in browser
d2d pr --draft        # Create as draft PR
d2d pr --base main    # Create PR to main (for demo→main merges)

# Utilities
d2d clean             # Remove caches and build artifacts
```

**Tip:** Run `d2d --help` or `d2d <command> --help` for more details on any command.

---

## First-Time Setup

After cloning, install dev dependencies and activate the pre-commit hooks:

```bash
pip install -e ".[dev]"
d2d hooks install     # or: pre-commit install + pre-commit install --hook-type commit-msg
```

Or use the interactive setup guide to check all dependencies:

```bash
d2d setup
```

You only need to do this once per clone. After this, hooks run automatically on every `git commit`.

---

## Branch Strategy

We use a three-tier branch strategy to ensure stability:

- **`main`** is the protected production branch (will be deployed to production Railway in the future). Direct pushes are blocked.
- **`demo`** is the integration and testing branch (currently deployed to Railway). Direct pushes are blocked.
- All work happens on **feature branches**, branched off `demo`.

Branch names should reflect the type and scope of the change:

```
feat/race-timer
fix/card-draw-crash
docs/update-readme
chore/bump-dependencies
```

**Workflow:**

```
main (future production)
 ↑
 └── merge ← demo (Railway deployment)
              ↑
              └── merge ← feat/your-feature (local dev)
                           ├── commits...
                           └── PR → demo (requires review + CI)
```

**Development environments:**

- **Feature branches**: Run locally using personal dev bot tokens
- **`demo` branch**: Deployed to Railway for integration testing
- **`main` branch**: Reserved for future production deployment

**Rules:**

- Never commit directly to `demo` or `main`. Both branches are protected and will reject direct pushes.
- All feature work branches off `demo` and merges back to `demo` via PR
- Once `demo` is in a stable state, merge it to `main` via PR
- Keep `demo` relatively stable — it's a shared testing environment

---

## Commit Messages

This project enforces the [Conventional Commits](https://www.conventionalcommits.org/) specification. Every commit message must follow this format:

```
<type>: <short description>

[optional body]

[optional footer]
```

### Allowed types

| Type | When to use |
|------|-------------|
| `feat` | A new feature or user-facing behaviour |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `style` | Formatting, whitespace — no logic change |
| `refactor` | Code restructure with no behaviour change |
| `test` | Adding or updating tests |
| `chore` | Dependency bumps, tooling, config |
| `ci` | Changes to GitHub Actions or CI config |
| `perf` | Performance improvements |
| `revert` | Reverting a previous commit |
| `build` | Build system changes (Dockerfile, pyproject.toml) |

### Examples

```bash
# Good
git commit -m "feat: add race timer to race engine"
git commit -m "fix: resolve card draw crash when inventory is empty"
git commit -m "chore: bump discord.py to 2.4"
git commit -m "test: add coverage for durability failure edge cases"

# Bad — will be rejected by the commit-msg hook
git commit -m "fix stuff"
git commit -m "wip"
git commit -m "."
```

### Streamlined Commit Workflow

The `d2d commit` command automates common commit tasks:

```bash
# Interactive commit (recommended for first-time users)
d2d commit

# Auto-stage all modified files and commit
d2d commit -a

# Stage, commit, and push in one command
d2d commit -ap

# Quick commit with type and message (skips interactive)
d2d commit -t feat -m "add race timer"
d2d commit -t fix -m "resolve card draw crash"
```

**What it does:**
- ✅ Validates you have changes to commit
- ✅ Optionally auto-stages modified files with `-a`
- ✅ Shows what will be committed
- ✅ Runs commitizen for interactive commits
- ✅ Optionally pushes after committing with `-p`
- ✅ Auto-sets upstream branch if needed

**Traditional commitizen** is still available:

```bash
cz commit   # or: git cz
```

Both methods enforce the conventional commit format and run pre-commit hooks automatically.

---

## Pre-commit Hooks

Pre-commit hooks run automatically before each `git commit`. They catch issues locally before they reach CI.

### What runs

| Hook | Stage | What it does |
|------|-------|-------------|
| `trailing-whitespace` | pre-commit | Strips trailing whitespace |
| `end-of-file-fixer` | pre-commit | Ensures files end with a newline |
| `check-yaml` | pre-commit | Validates YAML syntax |
| `check-merge-conflict` | pre-commit | Blocks commits with unresolved merge markers |
| `check-added-large-files` | pre-commit | Blocks files over 500 KB |
| `ruff` | pre-commit | Lints Python and auto-fixes where possible |
| `black` | pre-commit | Enforces code formatting |
| `commitizen` | commit-msg | Validates commit message format |

### Running hooks manually

```bash
# Run all hooks against staged files
d2d hooks run         # or: pre-commit run

# Run all hooks against every file in the repo
d2d hooks run --all   # or: pre-commit run --all-files

# Run a specific hook
pre-commit run ruff --all-files
```

### If a hook auto-fixes your files

Some hooks (ruff, trailing-whitespace, end-of-file-fixer) modify files in place. When that happens, the commit is aborted so you can review the changes. Simply re-stage and commit:

```bash
git add -p        # review the auto-fixes
git commit -m "feat: your message"
```

### Skipping hooks (emergencies only)

```bash
git commit --no-verify -m "chore: emergency hotfix"
```

Use this sparingly. CI will still run the same checks and your PR won't merge if they fail.

---

## Pull Requests

Every change must go through a pull request.

**Quick PR creation:**

```bash
# Create PR to demo with auto-filled content
d2d pr

# Open in browser to fill template manually
d2d pr --web

# Create as draft
d2d pr --draft
```

The `d2d pr` command automatically targets `demo` branch and fills in the PR title/body from your commits.

**For feature work:**

1. Push your feature branch: `git push -u origin feat/your-feature`
2. Create PR: `d2d pr` (or manually via GitHub)
3. Fill in the PR template — describe what changed and why
4. Ensure all CI checks pass (see below)
5. Request a review from at least one team member
6. Address any review feedback
7. Merge once approved and green

**For demo → main:**

1. Open a PR from `demo` to `main` when demo is stable: `d2d pr --base main`
2. Ensure all features in demo have been tested on Railway
3. Require thorough review before merging
4. This will eventually trigger production deployment

### PR title

PR titles should also follow conventional commit format, since the title is often used as the squash-merge commit message:

```
feat: add race timer to race engine
fix: resolve card draw crash when inventory is empty
```

---

## CI / GitHub Actions

Three jobs run on every push and pull request to `demo` and `main`:

| Job | What it checks |
|-----|---------------|
| **Pre-commit** | All pre-commit hooks (ruff, black, file hygiene) |
| **Lint** | Ruff linting + Black formatting check |
| **Test** | Full pytest suite with 70% coverage requirement |
| **Docker Build Test** | Dev and prod Docker images build successfully (runs after Test) |

All jobs must pass before a PR can be merged.

---

## Branch Protection

Both the `demo` and `main` branches have the following rules enforced via GitHub:

- **Direct pushes are blocked** — all changes must come through a PR
- **Force pushes are disabled** — history cannot be rewritten
- **Required status checks** — Pre-commit, Lint, and Test must all pass
- **Required review** — at least 1 approving review is required
- **Stale review dismissal** — new commits dismiss existing approvals, requiring a fresh review
- **Conversation resolution** — all PR comments must be resolved before merging
- **Branch must be up to date** — your branch must be current with the target branch before merging

**Additional notes:**

- `demo` is the primary target for feature PRs and runs on Railway
- `main` is reserved for stable releases and future production deployment
