










































# Contributing to Dare2Drive

This document covers the git workflow, commit standards, and tooling every contributor should know before opening a pull request.

---

## Table of Contents

- [Contributing to Dare2Drive](#contributing-to-dare2drive)
  - [Table of Contents](#table-of-contents)
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

## First-Time Setup

After cloning, install dev dependencies and activate the pre-commit hooks:

```bash
pip install -e ".[dev]"
pre-commit install                        # hooks for staged files
pre-commit install --hook-type commit-msg # hook for commit message validation
```

You only need to do this once per clone. After this, hooks run automatically on every `git commit`.

---

## Branch Strategy

- **`main`** is the protected production branch. Direct pushes are blocked.
- All work happens on feature branches, branched off `main`.
- Branch names should reflect the type and scope of the change:

```
feat/race-timer
fix/card-draw-crash
docs/update-readme
chore/bump-dependencies
```

**Workflow:**

```
main
 └── feat/your-feature        ← branch off main
      ├── commits...
      └── PR → main           ← merge via pull request (requires review + CI)
```

Never commit directly to `main`. The branch is protected and will reject direct pushes.

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

### Using Commitizen (optional but recommended)

[Commitizen](https://commitizen-tools.github.io/commitizen/) provides an interactive prompt that guides you through writing a valid commit message:

```bash
cz commit   # or: git cz
```

It walks you through selecting a type, writing a description, and optionally adding a body and footer — no need to remember the format manually.

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
pre-commit run

# Run all hooks against every file in the repo
pre-commit run --all-files

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

Every change to `main` must go through a pull request.

1. Push your branch and open a PR against `main`
2. Fill in the PR template — describe what changed and why
3. Ensure all CI checks pass (see below)
4. Request a review from at least one team member
5. Address any review feedback
6. Merge once approved and green

### PR title

PR titles should also follow conventional commit format, since the title is often used as the squash-merge commit message:

```
feat: add race timer to race engine
fix: resolve card draw crash when inventory is empty
```

---

## CI / GitHub Actions

Three jobs run on every push and pull request to `main`:

| Job | What it checks |
|-----|---------------|
| **Pre-commit** | All pre-commit hooks (ruff, black, file hygiene) |
| **Lint** | Ruff linting + Black formatting check |
| **Test** | Full pytest suite with 70% coverage requirement |
| **Docker Build Test** | Dev and prod Docker images build successfully (runs after Test) |

All jobs must pass before a PR can be merged.

---

## Branch Protection

The `main` branch has the following rules enforced via GitHub:

- **Direct pushes are blocked** — all changes must come through a PR
- **Force pushes are disabled** — history on `main` cannot be rewritten
- **Required status checks** — Pre-commit, Lint, and Test must all pass
- **Required review** — at least 1 approving review is required
- **Stale review dismissal** — new commits dismiss existing approvals, requiring a fresh review
- **Conversation resolution** — all PR comments must be resolved before merging
- **Branch must be up to date** — your branch must be current with `main` before merging
