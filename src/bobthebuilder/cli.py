"""CLI entrypoint for bobthebuilder."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .detector import detect_project
from .executor import execute_step
from .models import BuildStep, Ecosystem, RiskLevel
from .output import Output
from .strategies import get_steps_for_context
from .workspace import Workspace, WorkspaceRepo, clone_repo, create_workspace, load_workspace

app = typer.Typer(
    name="bob",
    help="Automatically set up any project for local development.",
    no_args_is_help=False,
)


def _find_bob_yaml(start: Path) -> Path | None:
    """Walk up from start looking for bob.yaml."""
    current = start.resolve()
    for _ in range(20):
        candidate = current / "bob.yaml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


_GIT_URL_RE = re.compile(
    r"^(https?://|git@|ssh://|git://)"
    r"|\.git$"
)


def _is_git_url(s: str) -> bool:
    return bool(_GIT_URL_RE.search(s))


def _url_to_dirname(url: str) -> str:
    """Extract a directory name from a git URL."""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


@app.command()
def init(
    repos: list[str] = typer.Argument(None, help="Paths to repos or git URLs to include"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Create a workspace by detecting repos. Accepts local paths or git URLs."""
    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    repo_paths: list[Path] = []
    clone_urls: list[tuple[str, str]] = []

    if not repos:
        # Auto-detect subdirectories
        repo_paths = [
            p
            for p in sorted(cwd.iterdir())
            if p.is_dir() and not p.name.startswith(".") and _looks_like_project(p)
        ]
        if not repo_paths:
            if _looks_like_project(cwd):
                repo_paths = [cwd]
            else:
                out.error("No projects found. Pass repo paths or git URLs as arguments.")
                raise typer.Exit(1)
    else:
        for r in repos:
            if _is_git_url(r):
                dirname = _url_to_dirname(r)
                clone_urls.append((r, dirname))
                out.info(f"Cloning {r} -> ./{dirname}")
            else:
                rp = Path(r).resolve()
                if not rp.is_dir():
                    out.error(f"Not a directory: {rp}")
                    raise typer.Exit(1)
                repo_paths.append(rp)

    ws = create_workspace(cwd, repo_paths=repo_paths, clone_urls=clone_urls)
    bob_yaml = cwd / "bob.yaml"
    ws.save(bob_yaml)

    out.workspace_created(ws, str(bob_yaml))
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

            # Use custom build steps if defined
            if ws_repo.custom_build_steps:
                results = _run_custom_steps(ws_repo, repo_path, out, dry_run)
            else:
                results = _build_single_repo(repo_path, out, dry_run, docker)
            all_results.extend(results)

        total_duration = time.monotonic() - total_start
        out.summary(all_results, total_duration)

        if any(not r.success for r in all_results):
            raise typer.Exit(1)
    else:
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
        ctx = detect_project(cwd)
        if ctx.ecosystems:
            eco = ctx.ecosystems[0].value
            pm = ctx.node_package_manager or ctx.python_tool
            out.detected([(str(cwd), eco, pm)])
        else:
            out.info("No project detected in current directory.")


@app.command()
def clean(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Remove build artifacts, dependency caches, and virtual environments."""
    from .cleaner import clean_project, find_cleanable_dirs

    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    bob_yaml = _find_bob_yaml(cwd)
    all_dirs: list[Path] = []

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent
        for ws_repo in ws.repos:
            repo_path = (ws_root / ws_repo.path).resolve()
            if repo_path.is_dir():
                all_dirs.extend(find_cleanable_dirs(repo_path))
    else:
        all_dirs = find_cleanable_dirs(cwd)

    if not all_dirs:
        out.info("Nothing to clean.")
        return

    if json_output:
        result_data = {
            "dry_run": dry_run,
            "dirs": [str(d) for d in all_dirs],
            "count": len(all_dirs),
        }
        if not dry_run:
            from .cleaner import clean_project
            result = clean_project(cwd, dry_run=False)
            result_data["removed"] = result.dirs_removed
            result_data["bytes_freed"] = result.bytes_freed
        print(json.dumps(result_data, indent=2))
        return

    for d in all_dirs:
        rel = d.relative_to(cwd) if d.is_relative_to(cwd) else d
        out.info(f"  {'[dim](would remove)[/dim] ' if dry_run else ''}{rel}")

    if not dry_run:
        from .cleaner import clean_project
        result = clean_project(cwd, dry_run=False)
        mb = result.bytes_freed / (1024 * 1024)
        out.info(f"Cleaned {result.dirs_removed} directories ({mb:.1f} MB freed)")
    else:
        out.info(f"Would clean {len(all_dirs)} directories (use without --dry-run to clean)")


@app.command()
def pull(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Pull latest changes for all repos in the workspace."""
    from .puller import pull_repos

    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    bob_yaml = _find_bob_yaml(cwd)
    if not bob_yaml:
        out.error("No bob.yaml found. Run 'bob init' first.")
        raise typer.Exit(1)

    ws = load_workspace(bob_yaml)
    ws_root = bob_yaml.parent

    repo_paths = [
        (ws_root / r.path).resolve()
        for r in ws.repos
        if (ws_root / r.path).resolve().is_dir()
    ]

    results = pull_repos(repo_paths)

    if json_output:
        print(json.dumps(
            {"results": [{"path": r.path, "success": r.success, "message": r.message} for r in results]},
            indent=2,
        ))
        return

    for r in results:
        name = Path(r.path).name
        if r.success:
            out.info(f"  [green]✓[/green] {name}: {r.message}")
        else:
            out.info(f"  [red]✗[/red] {name}: {r.message}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    """bobthebuilder - automatically set up any project for local development."""
    if version:
        print(f"bobthebuilder {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        build()


def _build_single_repo(repo_path: Path, out: Output, dry_run: bool, docker: bool):
    """Detect and build a single repo. Returns list of ExecutionResults."""
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
        result = execute_step(step, cwd=step.working_dir or str(repo_path), dry_run=dry_run)
        out.step_done(result)
        results.append(result)

        if not result.success and not dry_run:
            break

    return results


def _run_custom_steps(ws_repo: WorkspaceRepo, repo_path: Path, out: Output, dry_run: bool):
    """Run custom build_steps defined in bob.yaml."""
    out.info(f"[bold]{repo_path.name}[/bold] [dim](custom steps)[/dim]")

    results = []
    for step_def in ws_repo.custom_build_steps:
        cmd_str = step_def.get("command", "")
        name = step_def.get("name", cmd_str)
        command = cmd_str.split()

        step = BuildStep(
            name=name,
            command=command,
            description=f"Custom: {cmd_str}",
            ecosystem=Ecosystem(ws_repo.detected_ecosystem or "node"),
            risk_level=RiskLevel.MEDIUM,
        )
        out.step_start(step)
        result = execute_step(step, cwd=str(repo_path), dry_run=dry_run)
        out.step_done(result)
        results.append(result)

        if not result.success and not dry_run:
            break

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
        "Gemfile",
        "Makefile",
        "docker-compose.yml",
        "compose.yml",
    ]
    return any((path / m).exists() for m in markers)
