# Pull Request Workflow for Claude

When the user asks you to create a pull request, use the `d2d pr` command:

## Quick Commands

```bash
# Standard feature branch → demo PR
d2d pr

# Open in browser for manual template filling
d2d pr --web

# Create as draft PR
d2d pr --draft

# Demo → main PR (for releases)
d2d pr --base main
```

## Workflow Steps

1. **Ensure branch is pushed**: `git push -u origin <branch-name>`
2. **Run pre-checks**: `d2d check` (optional but recommended)
3. **Create PR**: `d2d pr` (defaults to demo branch)
4. **Verify created**: Check the PR URL in the output

## What the Command Does

- Automatically targets `demo` branch (the integration branch)
- Auto-fills PR title from latest commit message
- Auto-fills PR body from commit history
- Uses the project's PR template structure
- Validates GitHub CLI is installed and authenticated
- Prevents creating PRs from demo/main to themselves

## Prerequisites

The user needs:
- GitHub CLI installed: `gh --version`
- GitHub CLI authenticated: `gh auth status`
- Changes pushed to origin
- On a feature branch (not demo/main)

## Troubleshooting

If `gh` not found:
```bash
# macOS
brew install gh

# Windows
scoop install gh
# or: winget install GitHub.cli

# Then authenticate
gh auth login
```

## Branch Strategy Reminder

- **Feature branches** → `demo` (default, for all feature work)
- **`demo`** → `main` (only for stable releases, use `--base main`)
- Never create PRs from a branch to itself
