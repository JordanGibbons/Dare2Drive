# Git Workflow Quick Reference for Claude

## Complete Feature Development Workflow

### 1. Create Feature Branch
```bash
git checkout demo
git pull
git checkout -b feat/your-feature-name
```

### 2. Make Changes & Commit
```bash
# Make your code changes...

# Option A: Auto-stage and commit (fastest)
d2d commit -a

# Option B: Quick commit with message
d2d commit -a -t feat -m "add awesome feature"

# Option C: Manual staging + interactive commit
git add specific/files.py
d2d commit
```

### 3. Push & Create PR
```bash
# Push and create PR in one go
d2d commit -ap  # commits and pushes
d2d pr          # creates PR to demo

# Or do it separately
git push -u origin feat/your-feature-name
d2d pr
```

### 4. Review Process
- Wait for CI checks to pass
- Request reviews from team members
- Address feedback with additional commits
- Merge when approved

## Common Commands

### Daily Development
```bash
d2d test              # Run tests before committing
d2d lint --fix        # Auto-fix linting issues
d2d commit -a         # Stage all and commit
d2d commit -ap        # Stage, commit, and push
```

### Complete Quality Check
```bash
d2d check             # Run lint + format + test
d2d commit -ap        # If checks pass, commit and push
d2d pr                # Create PR
```

### Quick Fixes
```bash
# Make fix, test, commit, and push in sequence
d2d test
d2d commit -a -t fix -m "resolve issue with X"
git push
```

### Draft PRs
```bash
d2d pr --draft        # Create draft PR for early feedback
# When ready:
gh pr ready <pr-number>
```

## Branch Strategy

```
main (future production)
 ↑
 └── demo (Railway deployment) ← Your PRs target here
      ↑
      └── feat/your-feature ← Work here
```

## Commit Types Quick Reference

- `feat`: New feature or user-facing behavior
- `fix`: Bug fix
- `docs`: Documentation only
- `chore`: Dependencies, config, tooling
- `test`: Test additions or changes
- `refactor`: Code restructure, no behavior change
- `ci`: CI/CD changes

## Tips for Claude

When the user asks to:
- **"commit this"** → Use `d2d commit -a`
- **"commit and push"** → Use `d2d commit -ap`
- **"create a PR"** → Use `d2d pr`
- **"quick commit"** → Use `d2d commit -a -t <type> -m "<message>"`

Always ensure tests pass before committing:
```bash
d2d test && d2d commit -a
```
