"""CLI entrypoint for bobthebuilder."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .detector import detect_project
from .executor import execute_step
from .models import Ecosystem
from .output import Output
from .strategies import get_steps_for_context
from .workspace import Workspace, WorkspaceRepo, create_workspace, load_workspace

app = typer.Typer(
    name="bob",
    help="Automatically set up any project for local development.",
    no_args_is_help=False,
)


def _find_bob_yaml(start: Path) -> Path | None:
    """Walk up from start looking for bob.yaml."""
    current = start.resolve()
    for _ in range(20):  # safety limit
        candidate = current / "bob.yaml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


@app.command()
def init(
    repos: list[str] = typer.Argument(None, help="Paths to repos (or git URLs) to include"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Create a workspace by detecting repos."""
    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    if not repos:
        # Auto-detect: look for subdirectories that look like repos
        repo_paths = [
            p
            for p in sorted(cwd.iterdir())
            if p.is_dir() and not p.name.startswith(".") and _looks_like_project(p)
        ]
        if not repo_paths:
            # Maybe cwd itself is a single repo
            if _looks_like_project(cwd):
                repo_paths = [cwd]
            else:
                out.error("No projects found. Pass repo paths as arguments.")
                raise typer.Exit(1)
    else:
        repo_paths = [Path(r).resolve() for r in repos]
        # Validate paths exist
        for rp in repo_paths:
            if not rp.is_dir():
                out.error(f"Not a directory: {rp}")
                raise typer.Exit(1)

    ws = create_workspace(cwd, repo_paths)
    bob_yaml = cwd / "bob.yaml"
    ws.save(bob_yaml)

    out.workspace_created(ws, str(bob_yaml))

    # Also show detection results
    detection_info = [
        (r.path, r.detected_ecosystem or "unknown", r.detected_package_manager)
        for r in ws.repos
    ]
    out.detected(detection_info)


@app.command()
def build(
    repo: Optional[str] = typer.Argument(None, help="Build a specific repo (by path)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan without executing"),
    docker: bool = typer.Option(False, "--docker", help="Include Docker Compose services"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Set up project dependencies and build."""
    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    # Try to find bob.yaml for multi-repo workspace
    bob_yaml = _find_bob_yaml(cwd)

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent
        repos_to_build = ws.repos
        if repo:
            repos_to_build = [r for r in ws.repos if repo in r.path]
            if not repos_to_build:
                out.error(f"Repo '{repo}' not found in workspace")
                raise typer.Exit(1)

        all_results = []
        total_start = time.monotonic()

        for ws_repo in repos_to_build:
            repo_path = (ws_root / ws_repo.path).resolve()
            if not repo_path.is_dir():
                out.error(f"Repo path not found: {ws_repo.path}")
                continue
            results = _build_single_repo(repo_path, out, dry_run, docker)
            all_results.extend(results)

        total_duration = time.monotonic() - total_start
        out.summary(all_results, total_duration)

        if any(not r.success for r in all_results):
            raise typer.Exit(1)
    else:
        # Single repo mode - just build cwd
        total_start = time.monotonic()
        results = _build_single_repo(cwd, out, dry_run, docker)
        total_duration = time.monotonic() - total_start
        out.summary(results, total_duration)

        if any(not r.success for r in results):
            raise typer.Exit(1)


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show workspace status."""
    out = Output(json_mode=json_output)
    cwd = Path.cwd()

    bob_yaml = _find_bob_yaml(cwd)
    if bob_yaml:
        ws = load_workspace(bob_yaml)
        detection_info = [
            (r.path, r.detected_ecosystem or "unknown", r.detected_package_manager)
            for r in ws.repos
        ]
        out.detected(detection_info)
    else:
        # Single repo
        ctx = detect_project(cwd)
        if ctx.ecosystems:
            eco = ctx.ecosystems[0].value
            pm = ctx.node_package_manager or ctx.python_tool
            out.detected([(str(cwd), eco, pm)])
        else:
            out.info("No project detected in current directory.")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    """bobthebuilder - automatically set up any project for local development."""
    if version:
        print(f"bobthebuilder {__version__}")
        raise typer.Exit()
    # If no subcommand given, run build
    if ctx.invoked_subcommand is None:
        build()


def _build_single_repo(repo_path: Path, out: Output, dry_run: bool, docker: bool):
    """Detect and build a single repo. Returns list of ExecutionResults."""
    from .executor import ExecutionResult

    ctx = detect_project(repo_path)

    if not ctx.ecosystems and not ctx.env_example_files:
        out.info(f"[dim]Skipping {repo_path.name} (no ecosystem detected)[/dim]")
        return []

    steps = get_steps_for_context(ctx, docker_flag=docker)

    if not steps:
        out.info(f"[dim]No setup steps needed for {repo_path.name}[/dim]")
        return []

    eco_names = ", ".join(e.value for e in ctx.ecosystems)
    out.info(f"[bold]{repo_path.name}[/bold] [dim]({eco_names})[/dim]")
    out.plan(steps)

    results = []
    for step in steps:
        out.step_start(step)
        result = execute_step(step, cwd=str(repo_path), dry_run=dry_run)
        out.step_done(result)
        results.append(result)

        if not result.success and not dry_run:
            break  # stop on first failure for this repo

    return results


def _looks_like_project(path: Path) -> bool:
    """Quick check if a directory looks like a project."""
    markers = [
        "package.json",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "Makefile",
        "docker-compose.yml",
        "compose.yml",
    ]
    return any((path / m).exists() for m in markers)
