#!/usr/bin/env python3
"""Dare2Drive Developer CLI - Streamlined development commands."""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click


def run(cmd: str, check: bool = True, shell: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    return subprocess.run(cmd, shell=shell, check=check)


def run_quiet(cmd: str) -> bool:
    """Run a command quietly and return True if successful."""
    result = subprocess.run(
        cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def check_command(cmd: str) -> bool:
    """Check if a command exists."""
    return shutil.which(cmd) is not None


def print_logo():
    """Print the colorful D2D ASCII logo."""
    logo = r"""
██████╗ ██████╗ ██████╗
██╔══██╗╚════██╗██╔══██╗
██║  ██║ █████╔╝██║  ██║
██║  ██║██╔═══╝ ██║  ██║
██████╔╝███████╗██████╔╝
╚═════╝ ╚══════╝╚═════╝
"""
    lines = [line for line in logo.strip().split("\n") if line]
    # Sunset colors: deep red -> orange -> yellow -> magenta -> purple -> deep purple
    colors = ["red", "bright_red", "yellow", "magenta", "bright_magenta", "blue"]

    enc = sys.stdout.encoding or "utf-8"
    for i, line in enumerate(lines):
        safe = line.encode(enc, errors="replace").decode(enc)
        click.secho("    " + safe, fg=colors[i % len(colors)], bold=True)

    click.secho("    Dare 2 Drive", fg="white", bold=True)
    click.echo()


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0", prog_name="d2d")
@click.pass_context
def cli(ctx):
    """🏎️  Dare2Drive Developer CLI

    Streamlined commands for development, testing, and deployment.
    """
    # Show logo when no subcommand or when showing help
    if ctx.invoked_subcommand is None:
        print_logo()
        if not ctx.resilient_parsing:
            click.echo(ctx.get_help())


@cli.command()
def setup():
    """🔧 Interactive setup guide for new developers."""
    print_logo()
    click.secho("Setup Wizard", fg="cyan", bold=True)
    click.echo()

    checks = []

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info >= (3, 12) and sys.version_info < (3, 14):
        checks.append(("Python 3.12+", True, py_version))
    else:
        checks.append(("Python 3.12+", False, f"{py_version} (requires 3.12-3.13)"))

    # Git
    has_git = check_command("git")
    git_version = (
        subprocess.check_output(["git", "--version"], text=True).strip()
        if has_git
        else "Not installed"
    )
    checks.append(("Git", has_git, git_version))

    # Docker
    has_docker = check_command("docker")
    docker_version = (
        subprocess.check_output(["docker", "--version"], text=True).strip()
        if has_docker
        else "Not installed"
    )
    checks.append(("Docker", has_docker, docker_version))

    # Docker Compose
    has_compose = run_quiet("docker compose version")
    compose_version = (
        subprocess.check_output(["docker", "compose", "version"], text=True).strip()
        if has_compose
        else "Not installed"
    )
    checks.append(("Docker Compose", has_compose, compose_version))

    # Infisical CLI
    has_infisical = check_command("infisical")
    infisical_version = (
        subprocess.check_output(["infisical", "--version"], text=True).strip()
        if has_infisical
        else "Not installed"
    )
    checks.append(("Infisical CLI", has_infisical, infisical_version))

    # GitHub CLI
    has_gh = check_command("gh")
    gh_version = (
        subprocess.check_output(["gh", "--version"], text=True).split("\n")[0]
        if has_gh
        else "Not installed (optional)"
    )
    checks.append(("GitHub CLI", has_gh, gh_version))

    # Display results
    click.echo("Checking dependencies:")
    click.echo()
    for name, status, version in checks:
        icon = "✓" if status else "✗"
        color = "green" if status else "red"
        click.secho(f"  {icon} {name:<20} {version}", fg=color)

    click.echo()

    # Installation instructions for missing deps
    missing_required = [name for name, status, _ in checks[:5] if not status]
    if missing_required:
        click.secho("Missing required dependencies!", fg="red", bold=True)
        click.echo()
        click.echo("Installation instructions:")
        click.echo()

        if not has_docker:
            click.echo("  Docker: https://docs.docker.com/get-docker/")
        if not has_infisical:
            system = platform.system()
            if system == "Darwin":
                click.echo("  Infisical: brew install infisical/infisical-cli/infisical")
            elif system == "Windows":
                click.echo("  Infisical: scoop install infisical")
            else:
                click.echo("  Infisical: https://infisical.com/docs/cli/overview")
        if not has_gh:
            click.echo("  GitHub CLI (optional): https://cli.github.com/ or 'brew install gh'")

        return

    click.secho("All required dependencies installed! ✨", fg="green", bold=True)
    click.echo()

    # Check if in virtualenv
    in_venv = sys.prefix != sys.base_prefix or hasattr(sys, "real_prefix")
    if not in_venv:
        click.secho("⚠️  Not in a virtual environment", fg="yellow")
        click.echo("Consider creating one:")
        click.echo("  python -m venv venv")
        if platform.system() == "Windows":
            click.echo("  .\\venv\\Scripts\\activate")
        else:
            click.echo("  source venv/bin/activate")
        click.echo()

    # Project dependencies
    click.echo("Next steps:")
    click.echo()
    click.echo("  1. Install dev dependencies:")
    click.echo('     pip install -e ".[dev]"')
    click.echo()
    click.echo("  2. Set up pre-commit hooks:")
    click.echo("     d2d hooks --install")
    click.echo()
    click.echo("  3. Log in to Infisical:")
    click.echo("     infisical login")
    click.echo()
    click.echo("  4. Start local development environment:")
    click.echo("     d2d up")
    click.echo()
    click.secho("🏁 Happy coding!", fg="cyan", bold=True)


@cli.command()
@click.option("--watch", "-w", is_flag=True, help="Run in watch mode (requires pytest-watch)")
@click.option("--cov/--no-cov", default=True, help="Run with coverage (default: yes)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.argument("path", required=False)
def test(watch: bool, cov: bool, verbose: bool, path: str):
    """🧪 Run the test suite."""
    if watch:
        click.echo("Running tests in watch mode...")
        run("ptw -- --testmon")
        return

    cmd = ["pytest"]
    if cov:
        cmd.append("--cov")
    if verbose:
        cmd.append("-v")
    if path:
        cmd.append(path)

    click.echo("Running tests...")
    run(" ".join(cmd))


@cli.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible")
def lint(fix: bool):
    """🔍 Run ruff linter."""
    cmd = "ruff check ."
    if fix:
        cmd += " --fix"
        click.echo("Running ruff with auto-fix...")
    else:
        click.echo("Running ruff...")
    run(cmd)


@cli.command()
@click.option("--check", is_flag=True, help="Check formatting without modifying files")
def format(check: bool):
    """✨ Format code with black."""
    if check:
        click.echo("Checking code formatting...")
        run("black --check .")
    else:
        click.echo("Formatting code...")
        run("black .")


@cli.group()
def hooks():
    """🔗 Manage pre-commit hooks."""
    pass


@hooks.command(name="install")
def hooks_install():
    """Install pre-commit hooks."""
    click.echo("Installing pre-commit hooks...")
    run("pre-commit install")
    run("pre-commit install --hook-type commit-msg")
    click.secho("✓ Hooks installed!", fg="green")


@hooks.command(name="run")
@click.option("--all", "all_files", is_flag=True, help="Run on all files (not just staged)")
def hooks_run(all_files: bool):
    """Run pre-commit hooks manually."""
    cmd = "pre-commit run"
    if all_files:
        cmd += " --all-files"
        click.echo("Running hooks on all files...")
    else:
        click.echo("Running hooks on staged files...")
    run(cmd, check=False)


@hooks.command(name="update")
def hooks_update():
    """Update pre-commit hook versions."""
    click.echo("Updating pre-commit hooks...")
    run("pre-commit autoupdate")


@cli.command()
@click.option("--build", "-b", is_flag=True, help="Rebuild containers")
@click.option("--detach", "-d", is_flag=True, help="Run in background")
@click.option(
    "--monitoring",
    "-m",
    is_flag=True,
    help="Also start Prometheus + Grafana for local metrics testing",
)
def up(build: bool, detach: bool, monitoring: bool):
    """🚀 Start Docker Compose services."""
    print_logo()
    cmd = "infisical run --env=dev -- docker compose"
    if monitoring:
        cmd += " --profile monitoring"
    cmd += " up"
    if build:
        cmd += " --build"
    if detach:
        cmd += " -d"

    click.echo("Starting services...")
    run(cmd)


@cli.command()
@click.option("--volumes", "-v", is_flag=True, help="Remove volumes too")
def down(volumes: bool):
    """🛑 Stop Docker Compose services."""
    cmd = "docker compose --profile monitoring down"
    if volumes:
        cmd += " -v"
        click.echo("Stopping services and removing volumes...")
    else:
        click.echo("Stopping services...")
    run(cmd)


@cli.command()
@click.option("--dev", is_flag=True, help="Build dev image (default)")
@click.option("--prod", is_flag=True, help="Build production image")
def build(dev: bool, prod: bool):
    """🔨 Build Docker images."""
    if prod:
        click.echo("Building production image...")
        run("docker build -f docker/Dockerfile.prod -t dare2drive-prod .")
    else:
        click.echo("Building development image...")
        run("docker build -f docker/Dockerfile.dev -t dare2drive-dev .")


@cli.command()
@click.argument("revision", default="head")
def migrate(revision: str):
    """🗄️  Run database migrations."""
    click.echo(f"Running migrations to {revision}...")
    run(f"alembic upgrade {revision}")


@cli.command()
@click.option("--message", "-m", required=True, help="Migration message")
def makemigration(message: str):
    """📝 Create a new database migration."""
    click.echo(f"Creating migration: {message}")
    run(f'alembic revision --autogenerate -m "{message}"')


@cli.command()
def seed():
    """🌱 Seed the database with card data."""
    click.echo("Seeding database...")
    run("python scripts/seed_cards.py")


@cli.command()
@click.option(
    "--type",
    "-t",
    type=click.Choice(["feat", "fix", "docs", "chore", "test", "refactor", "ci"]),
    help="Commit type (skips interactive if provided with --message)",
)
@click.option("--message", "-m", help="Commit message (requires --type)")
@click.option("--add", "-a", is_flag=True, help="Automatically stage all modified files")
@click.option("--push", "-p", is_flag=True, help="Push after committing")
@click.option("--no-verify", is_flag=True, help="Skip pre-commit hooks (use sparingly)")
def commit(type: str, message: str, add: bool, push: bool, no_verify: bool):
    """💬 Smart commit with auto-staging and pushing.

    Examples:
      d2d commit                            # Interactive commitizen
      d2d commit -a                         # Stage all changes first
      d2d commit -t feat -m "add feature"   # Quick commit
      d2d commit -ap                        # Stage all, commit, and push
    """
    # Check if commitizen is available
    if not check_command("cz"):
        click.secho("✗ Commitizen not installed", fg="red")
        click.echo('Install: pip install -e ".[dev]"')
        sys.exit(1)

    if add:
        # Auto-stage modified and deleted files
        click.echo("Staging all changes...")
        modified_result = subprocess.run(
            "git status --porcelain", shell=True, capture_output=True, text=True
        )

        if modified_result.stdout.strip():
            run("git add -u")  # Stage modified and deleted files
            click.secho("✓ Staged all modified files", fg="green")
        else:
            click.secho("✗ No changes to stage", fg="yellow")
            sys.exit(0)

    # Check if there are staged changes
    staged_result = subprocess.run(
        "git diff --cached --name-only", shell=True, capture_output=True, text=True
    )

    if not staged_result.stdout.strip():
        click.secho("✗ No staged changes to commit", fg="yellow")
        click.echo("Stage files with: git add <files>")
        click.echo("Or use: d2d commit -a (to stage all modified files)")
        sys.exit(0)

    # Show what will be committed
    click.echo()
    click.secho("Files to commit:", fg="cyan")
    run("git diff --cached --name-status", check=False)
    click.echo()

    # Build commit command
    if message and type:
        # Quick commit with type and message
        commit_msg = f"{type}: {message}"
        cmd = f'git commit -m "{commit_msg}"'
        if no_verify:
            cmd += " --no-verify"

        click.secho(f"Creating commit: {commit_msg}", fg="cyan")
        result = subprocess.run(cmd, shell=True, check=False)

        if result.returncode != 0:
            click.secho("✗ Commit failed", fg="red")
            sys.exit(1)
    elif message and not type:
        click.secho("✗ --message requires --type", fg="red")
        click.echo("Example: d2d commit -t feat -m 'add new feature'")
        sys.exit(1)
    else:
        # Interactive commitizen
        if type:
            click.echo(f"Creating {type} commit (interactive)...")
        else:
            click.echo("Interactive commit...")

        cmd = "cz commit"
        if no_verify:
            cmd += " -- --no-verify"

        result = subprocess.run(cmd, shell=True, check=False)

        if result.returncode != 0:
            click.secho("✗ Commit cancelled or failed", fg="yellow")
            sys.exit(1)

    click.secho("✓ Commit created successfully!", fg="green")

    # Push if requested
    if push:
        click.echo()
        click.echo("Pushing to remote...")

        # Check if branch has upstream
        branch_result = subprocess.run(
            "git rev-parse --abbrev-ref --symbolic-full-name @{u}",
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )

        if branch_result.returncode != 0:
            # No upstream, set it
            current_branch = subprocess.run(
                "git branch --show-current",
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            click.echo(f"Setting upstream to origin/{current_branch}...")
            push_result = subprocess.run(
                f"git push -u origin {current_branch}", shell=True, check=False
            )
        else:
            push_result = subprocess.run("git push", shell=True, check=False)

        if push_result.returncode == 0:
            click.secho("✓ Pushed to remote!", fg="green")
        else:
            click.secho("✗ Push failed", fg="red")
            sys.exit(1)


@cli.command()
def logs():
    """📋 View Docker Compose logs."""
    click.echo("Showing logs (Ctrl+C to exit)...")
    run("docker compose logs -f", check=False)


@cli.command()
@click.argument("service", type=click.Choice(["bot", "api", "postgres", "redis"]))
def shell(service: str):
    """🐚 Open a shell in a running container."""
    click.echo(f"Opening shell in {service} container...")
    run(f"docker compose exec {service} /bin/bash", check=False)


@cli.command()
def db():
    """🗄️  Open PostgreSQL shell."""
    click.echo("Opening database shell...")
    run("docker compose exec postgres psql -U postgres -d dare2drive", check=False)


@cli.command()
def clean():
    """🧹 Clean up generated files and caches."""
    click.echo("Cleaning up...")

    patterns = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        ".pytest_cache",
        ".coverage",
        "coverage.xml",
        "htmlcov",
        ".mypy_cache",
        ".ruff_cache",
        "*.egg-info",
        "dist",
        "build",
    ]

    for pattern in patterns:
        for path in Path(".").glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
                click.echo(f"  Removed {path}/")
            else:
                path.unlink()
                click.echo(f"  Removed {path}")

    click.secho("✓ Cleanup complete!", fg="green")


@cli.command()
def check():
    """✅ Run all quality checks (lint + format check + test)."""
    print_logo()
    click.secho("Running all quality checks...", fg="cyan", bold=True)
    click.echo()

    checks = [
        ("Ruff linting", "ruff check ."),
        ("Black formatting", "black --check ."),
        ("Tests", "pytest --cov"),
    ]

    failed = []

    for name, cmd in checks:
        click.echo(f"→ {name}...")
        result = subprocess.run(cmd, shell=True, check=False)
        if result.returncode != 0:
            failed.append(name)
            click.secho(f"  ✗ {name} failed", fg="red")
        else:
            click.secho(f"  ✓ {name} passed", fg="green")
        click.echo()

    if failed:
        click.secho(f"❌ {len(failed)} check(s) failed: {', '.join(failed)}", fg="red", bold=True)
        sys.exit(1)
    else:
        click.echo()
        click.secho("    ╔═══════════════════════════╗", fg="green", bold=True)
        click.secho("    ║  ✅ ALL CHECKS PASSED! ✅  ║", fg="green", bold=True)
        click.secho("    ╚═══════════════════════════╝", fg="green", bold=True)
        click.echo()


@cli.command()
@click.option("--base", "-b", default="demo", help="Base branch to merge into (default: demo)")
@click.option("--draft", "-d", is_flag=True, help="Create as draft PR")
@click.option("--web", "-w", is_flag=True, help="Open in web browser to fill template")
def pr(base: str, draft: bool, web: bool):
    """🔀 Create a pull request to demo branch."""
    if not check_command("gh"):
        click.secho("✗ GitHub CLI (gh) not installed", fg="red")
        click.echo("Install: https://cli.github.com/")
        sys.exit(1)

    # Check if user is authenticated
    if not run_quiet("gh auth status"):
        click.secho("✗ Not authenticated with GitHub", fg="red")
        click.echo("Run: gh auth login")
        sys.exit(1)

    # Get current branch name
    result = subprocess.run(
        "git branch --show-current", shell=True, capture_output=True, text=True, check=True
    )
    current_branch = result.stdout.strip()

    if current_branch == base:
        click.secho(f"✗ Cannot create PR from {base} to itself", fg="red")
        click.echo("Switch to a feature branch first: git checkout -b feat/your-feature")
        sys.exit(1)

    if current_branch == "main":
        click.secho("⚠️  You're on main branch", fg="yellow")
        if base != "demo":
            click.echo(f"Creating PR: main → {base}")
        else:
            click.echo("Creating PR: main → demo")
            click.echo("(This should be for stable releases only)")

    # Get latest commit message for title suggestion
    result = subprocess.run(
        "git log -1 --pretty=%s", shell=True, capture_output=True, text=True, check=True
    )
    suggested_title = result.stdout.strip()

    click.echo()
    click.secho(f"📋 Creating PR: {current_branch} → {base}", fg="cyan", bold=True)
    click.echo()
    click.echo(f"Suggested title: {suggested_title}")
    click.echo()

    # Build gh pr create command
    cmd = ["gh", "pr", "create", "--base", base]

    if draft:
        cmd.append("--draft")

    if web:
        # Open in web browser to fill template manually
        cmd.append("--web")
        click.echo("Opening PR in web browser...")
    else:
        # Use interactive mode in terminal
        cmd.extend(["--fill"])  # Auto-fill title and body from commits
        click.echo("Creating PR with auto-generated content...")
        click.echo("(You can edit the PR description after creation)")

    # Run the command
    result = subprocess.run(cmd, check=False)

    if result.returncode == 0:
        click.echo()
        click.secho("✓ Pull request created!", fg="green", bold=True)
        click.echo()
        click.echo("Next steps:")
        click.echo("  • Review the PR description and edit if needed")
        click.echo("  • Request reviews from team members")
        click.echo("  • Wait for CI checks to pass")
    else:
        click.echo()
        click.secho("✗ Failed to create PR", fg="red")
        click.echo("Check the error message above for details")
        sys.exit(1)


if __name__ == "__main__":
    cli()
