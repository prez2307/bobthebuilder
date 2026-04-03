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

worktree_app = typer.Typer(
    name="worktree",
    help="Manage git worktrees across workspace repos.",
)
app.add_typer(worktree_app, name="worktree")


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
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Build repos in parallel"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Skip repos with unchanged lockfiles"),
    stream: bool = typer.Option(False, "--stream", help="Output NDJSON events (streaming)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Set up project dependencies and build."""
    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    streamer = None
    if stream:
        from .streaming import StreamingOutput
        streamer = StreamingOutput()

    bob_yaml = _find_bob_yaml(cwd)

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent

        # Load cache for incremental builds
        cache = None
        if incremental:
            from .cache import BuildCache
            cache = BuildCache.load(ws_root)

        repos_to_build = ws.repos
        if repo:
            repos_to_build = [r for r in ws.repos if repo in r.path]
            if not repos_to_build:
                out.error(f"Repo '{repo}' not found in workspace")
                raise typer.Exit(1)

        # Resolve build order from dependency graph
        repos_to_build = _resolve_build_order(repos_to_build, ws)

        if streamer:
            streamer.emit_workspace_start(ws.name, [r.path for r in repos_to_build])

        total_start = time.monotonic()

        if parallel and len(repos_to_build) > 1:
            all_results = _build_parallel(
                repos_to_build, ws_root, ws, out, dry_run, docker, cache, streamer,
            )
        else:
            all_results = _build_sequential(
                repos_to_build, ws_root, out, dry_run, docker, cache, streamer,
            )

        total_duration = time.monotonic() - total_start

        # Save cache
        if cache:
            cache.save(ws_root)

        if streamer:
            streamer.emit_workspace_done(ws.name, all(r.success for r in all_results), total_duration)
        else:
            out.summary(all_results, total_duration)

        if any(not r.success for r in all_results):
            raise typer.Exit(1)
    else:
        total_start = time.monotonic()
        results = _build_single_repo(cwd, out, dry_run, docker, streamer=streamer)
        total_duration = time.monotonic() - total_start

        if not streamer:
            out.summary(results, total_duration)

        if any(not r.success for r in results):
            raise typer.Exit(1)


@app.command()
def test(
    repo: Optional[str] = typer.Argument(None, help="Test a specific repo (by path or name)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show detected test command without executing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Detect and run tests."""
    from .tester import detect_all_test_commands, detect_test_command

    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()
    bob_yaml = _find_bob_yaml(cwd)

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent

        if repo:
            matches = [r for r in ws.repos if repo in r.path or repo == Path(r.path).name]
            if not matches:
                out.error(f"Repo '{repo}' not found in workspace")
                raise typer.Exit(1)
            target_path = (ws_root / matches[0].path).resolve()
        elif len(ws.repos) == 1:
            target_path = (ws_root / ws.repos[0].path).resolve()
        else:
            # Show all testable repos (including subproject ecosystems)
            configs = []
            for ws_repo in ws.repos:
                rp = (ws_root / ws_repo.path).resolve()
                if rp.is_dir():
                    for config in detect_all_test_commands(rp):
                        configs.append((ws_repo.path, config))

            if json_output:
                print(json.dumps({
                    "configs": [{"repo": p, **c.to_dict()} for p, c in configs],
                }, indent=2))
                return

            if not configs:
                out.error("No testable projects detected.")
                raise typer.Exit(1)

            out.info("[bold]Testable projects:[/bold]")
            for repo_path, config in configs:
                name = Path(repo_path).name
                out.info(f"  [cyan]{name}[/cyan]: {config.description}")
            out.info("\nRun tests for a specific repo: [bold]bob test <repo-name>[/bold]")
            return
    else:
        target_path = cwd

    if not target_path.is_dir():
        out.error(f"Directory not found: {target_path}")
        raise typer.Exit(1)

    all_configs = detect_all_test_commands(target_path)
    if not all_configs:
        out.error(f"Could not detect test command for {target_path.name}.")
        raise typer.Exit(1)

    config = all_configs[0]
    cmd_str = " ".join(config.command)

    if dry_run:
        if json_output:
            print(json.dumps({"configs": [c.to_dict() for c in all_configs]}, indent=2))
        else:
            for c in all_configs:
                out.info(f"[bold]{Path(c.path).name}[/bold] [dim]({c.ecosystem})[/dim]")
                out.info(f"  Would run: [cyan]{' '.join(c.command)}[/cyan]")
        return

    if not quiet and not json_output:
        out.info(f"[bold]{target_path.name}[/bold] [dim]({config.ecosystem})[/dim]")
        out.info(f"  [bold blue]>[/bold blue] {cmd_str}")

    # Run tests using the runner's streaming approach
    from .runner import RunConfig, run_app

    run_config = RunConfig(
        path=config.path,
        command=config.command,
        description=config.description,
        ecosystem=config.ecosystem,
    )
    exit_code = run_app(run_config)
    if exit_code != 0:
        raise typer.Exit(exit_code)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Check tool versions and environment health."""
    from .doctor import check_repo

    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    bob_yaml = _find_bob_yaml(cwd)
    results = []

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent
        for ws_repo in ws.repos:
            repo_path = (ws_root / ws_repo.path).resolve()
            if repo_path.is_dir():
                results.append(check_repo(repo_path))
    else:
        results.append(check_repo(cwd))

    if json_output:
        all_healthy = all(r.healthy for r in results)
        print(json.dumps({
            "healthy": all_healthy,
            "results": [r.to_dict() for r in results],
        }, indent=2))
        if not all_healthy:
            raise typer.Exit(1)
        return

    for r in results:
        status = "[green]healthy[/green]" if r.healthy else "[red]unhealthy[/red]"
        out.info(f"  [bold]{r.repo}[/bold] [dim]({r.ecosystem})[/dim] {status}")

        for check in r.checks:
            if check.installed:
                version_info = f"[dim]{check.version}[/dim]"
                wanted = ""
                if check.wanted_version:
                    wanted = f" [yellow](wants {check.wanted_version})[/yellow]"
                out.info(f"    [green]✓[/green] {check.name} {version_info}{wanted}")
            else:
                req = " [red](required)[/red]" if check.required else " [dim](optional)[/dim]"
                out.info(f"    [red]✗[/red] {check.name} not found{req}")

        for warning in r.warnings:
            out.info(f"    [yellow]![/yellow] {warning}")

    if any(not r.healthy for r in results):
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

        if json_output:
            from .monorepo import detect_monorepo
            status_data: dict = ws.to_dict()
            # Add monorepo info
            ws_root = bob_yaml.parent
            for i, ws_repo in enumerate(ws.repos):
                repo_path = (ws_root / ws_repo.path).resolve()
                if repo_path.is_dir():
                    mono = detect_monorepo(repo_path)
                    if mono:
                        status_data["repos"][i]["monorepo"] = mono.to_dict()
            print(json.dumps(status_data, indent=2))
            return

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


@app.command()
def run(
    repo: Optional[str] = typer.Argument(None, help="Run a specific repo (by path or name)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show detected run command without executing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Detect and run the application."""
    from .runner import detect_run_command, run_app

    out = Output(json_mode=json_output, quiet=quiet)
    cwd = Path.cwd()

    bob_yaml = _find_bob_yaml(cwd)

    if bob_yaml:
        ws = load_workspace(bob_yaml)
        ws_root = bob_yaml.parent

        if repo:
            # Run a specific repo
            matches = [r for r in ws.repos if repo in r.path or repo == Path(r.path).name]
            if not matches:
                out.error(f"Repo '{repo}' not found in workspace")
                raise typer.Exit(1)
            target_path = (ws_root / matches[0].path).resolve()
        elif len(ws.repos) == 1:
            target_path = (ws_root / ws.repos[0].path).resolve()
        else:
            # Multiple repos — show what's available
            configs = []
            for ws_repo in ws.repos:
                rp = (ws_root / ws_repo.path).resolve()
                if rp.is_dir():
                    config = detect_run_command(rp)
                    if config:
                        configs.append((ws_repo.path, config))

            if json_output:
                print(json.dumps({
                    "configs": [{"repo": p, **c.to_dict()} for p, c in configs],
                }, indent=2))
                return

            if not configs:
                out.error("No runnable projects detected. Specify a repo with 'bob run <repo>'.")
                raise typer.Exit(1)

            out.info("[bold]Runnable projects:[/bold]")
            for repo_path, config in configs:
                name = Path(repo_path).name
                out.info(f"  [cyan]{name}[/cyan]: {config.description}")
            out.info("\nRun a specific repo: [bold]bob run <repo-name>[/bold]")
            return
    else:
        target_path = cwd

    if not target_path.is_dir():
        out.error(f"Directory not found: {target_path}")
        raise typer.Exit(1)

    config = detect_run_command(target_path)
    if not config:
        out.error(f"Could not detect how to run {target_path.name}. No known run script or entry point found.")
        raise typer.Exit(1)

    cmd_str = " ".join(config.command)

    if dry_run:
        if json_output:
            print(json.dumps(config.to_dict(), indent=2))
        else:
            out.info(f"[bold]{target_path.name}[/bold] [dim]({config.ecosystem})[/dim]")
            out.info(f"  Would run: [cyan]{cmd_str}[/cyan]")
        return

    if not quiet and not json_output:
        out.info(f"[bold]{target_path.name}[/bold] [dim]({config.ecosystem})[/dim]")
        out.info(f"  [bold blue]>[/bold blue] {cmd_str}")

    exit_code = run_app(config)
    if exit_code != 0:
        raise typer.Exit(exit_code)


@app.command()
def mcp(
) -> None:
    """Start MCP server for AI agent tool integration."""
    from .mcp_server import create_mcp_server
    server = create_mcp_server()
    server.run_stdio()


# --- Worktree subcommands ---


@worktree_app.command("create")
def worktree_create(
    branch: str = typer.Argument(..., help="Branch name for the worktrees"),
    repo: Optional[str] = typer.Argument(None, help="Specific repo (by name). Omit for all repos."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Create worktrees for workspace repos on a branch."""
    from .worktree import create_worktrees

    out = Output(json_mode=json_output, quiet=quiet)
    repo_paths = _get_worktree_repo_paths(out, repo)

    results = create_worktrees(repo_paths, branch)

    if json_output:
        print(json.dumps({"results": [r.to_dict() for r in results]}, indent=2))
        return

    for r in results:
        if r.success:
            out.info(f"  [green]✓[/green] {r.repo}: {r.message}")
            if r.worktree_path:
                out.info(f"    [dim]{r.worktree_path}[/dim]")
        else:
            out.info(f"  [red]✗[/red] {r.repo}: {r.message}")

    if any(not r.success for r in results):
        raise typer.Exit(1)


@worktree_app.command("list")
def worktree_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """List worktrees for all workspace repos."""
    from .worktree import list_worktrees

    out = Output(json_mode=json_output, quiet=quiet)
    repo_paths = _get_worktree_repo_paths(out)

    results = list_worktrees(repo_paths)

    if json_output:
        print(json.dumps({"results": [r.to_dict() for r in results]}, indent=2))
        return

    for r in results:
        if not r.success:
            out.info(f"  [red]✗[/red] {r.repo}: {r.message}")
            continue
        out.info(f"  [bold]{r.repo}[/bold]")
        for wt in r.worktrees:
            branch = wt.branch or "(detached)"
            short_commit = wt.commit[:8] if wt.commit else ""
            out.info(f"    [cyan]{branch}[/cyan] [dim]{short_commit}[/dim] {wt.path}")


@worktree_app.command("remove")
def worktree_remove(
    branch: str = typer.Argument(..., help="Branch name of worktrees to remove"),
    repo: Optional[str] = typer.Argument(None, help="Specific repo (by name). Omit for all repos."),
    force: bool = typer.Option(False, "--force", "-f", help="Force removal even with uncommitted changes"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Remove worktrees for a branch across workspace repos."""
    from .worktree import remove_worktrees

    out = Output(json_mode=json_output, quiet=quiet)
    repo_paths = _get_worktree_repo_paths(out, repo)

    results = remove_worktrees(repo_paths, branch, force=force)

    if json_output:
        print(json.dumps({"results": [r.to_dict() for r in results]}, indent=2))
        return

    for r in results:
        if r.success:
            out.info(f"  [green]✓[/green] {r.repo}: {r.message}")
        else:
            out.info(f"  [red]✗[/red] {r.repo}: {r.message}")

    if any(not r.success for r in results):
        raise typer.Exit(1)


def _get_worktree_repo_paths(out: Output, repo: str | None = None) -> list[Path]:
    """Get repo paths from workspace, optionally filtering to a specific repo."""
    cwd = Path.cwd()
    bob_yaml = _find_bob_yaml(cwd)
    if not bob_yaml:
        out.error("No bob.yaml found. Run 'bob init' first.")
        raise typer.Exit(1)

    ws = load_workspace(bob_yaml)
    ws_root = bob_yaml.parent

    if repo:
        matches = [
            r for r in ws.repos
            if repo in r.path or repo == Path(r.path).name
        ]
        if not matches:
            out.error(f"Repo '{repo}' not found in workspace")
            raise typer.Exit(1)
        return [(ws_root / m.path).resolve() for m in matches]

    return [
        (ws_root / r.path).resolve()
        for r in ws.repos
        if (ws_root / r.path).resolve().is_dir()
    ]


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


# --- Internal build helpers ---


def _build_single_repo(repo_path: Path, out: Output, dry_run: bool, docker: bool, streamer=None):
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

    if streamer:
        streamer.emit_build_start(repo_path.name, len(steps))

    results = []
    for step in steps:
        out.step_start(step)
        if streamer:
            streamer.emit_step_start(repo_path.name, step.name, step.command)
        result = execute_step(step, cwd=step.working_dir or str(repo_path), dry_run=dry_run)
        out.step_done(result)
        if streamer:
            streamer.emit_step_done(
                repo_path.name, step.name, result.success, result.duration_s,
                result.exit_code, result.error,
            )
        results.append(result)

        if not result.success and not dry_run:
            break

    if streamer:
        streamer.emit_build_done(
            repo_path.name,
            all(r.success for r in results),
            sum(r.duration_s for r in results),
        )

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


def _run_hooks(ws_repo: WorkspaceRepo, repo_path: Path, phase: str, timing: str, out: Output, dry_run: bool):
    """Run pre/post hooks for a phase. Returns list of ExecutionResults."""
    from .hooks import HookConfig, run_hook

    hook_config = HookConfig.from_dict(ws_repo.hooks)
    pre, post = hook_config.get_hooks(phase)

    command = pre if timing == "pre" else post
    if not command:
        return []

    hook_name = f"{timing}_{phase}"
    out.info(f"  [dim]hook: {hook_name}[/dim]")
    result = run_hook(hook_name, command, cwd=str(repo_path), dry_run=dry_run)
    out.step_done(result)
    return [result]


def _build_sequential(repos_to_build, ws_root, out, dry_run, docker, cache, streamer):
    """Build repos sequentially."""
    from .executor import ExecutionResult

    all_results: list[ExecutionResult] = []

    for ws_repo in repos_to_build:
        repo_path = (ws_root / ws_repo.path).resolve()
        if not repo_path.is_dir():
            out.error(f"Repo path not found: {ws_repo.path}")
            continue

        # Incremental: skip if unchanged
        if cache and cache.is_up_to_date(repo_path, ws_repo.detected_ecosystem):
            out.info(f"[dim]Skipping {repo_path.name} (unchanged)[/dim]")
            if streamer:
                streamer.emit_cache_hit(repo_path.name)
            continue

        # Pre-build hooks
        hook_results = _run_hooks(ws_repo, repo_path, "build", "pre", out, dry_run)
        all_results.extend(hook_results)
        if hook_results and not hook_results[0].success and not dry_run:
            continue

        # Build
        if ws_repo.custom_build_steps:
            results = _run_custom_steps(ws_repo, repo_path, out, dry_run)
        else:
            results = _build_single_repo(repo_path, out, dry_run, docker, streamer=streamer)
        all_results.extend(results)

        # Post-build hooks
        if all(r.success for r in results):
            hook_results = _run_hooks(ws_repo, repo_path, "build", "post", out, dry_run)
            all_results.extend(hook_results)

        # Record in cache
        if cache:
            success = all(r.success for r in results)
            cache.record_build(repo_path, ws_repo.detected_ecosystem, success)

    return all_results


def _build_parallel(repos_to_build, ws_root, ws, out, dry_run, docker, cache, streamer):
    """Build repos in parallel using thread pool."""
    from .parallel import build_repos_parallel

    tasks = []
    for ws_repo in repos_to_build:
        repo_path = (ws_root / ws_repo.path).resolve()
        if not repo_path.is_dir():
            continue

        if cache and cache.is_up_to_date(repo_path, ws_repo.detected_ecosystem):
            out.info(f"[dim]Skipping {repo_path.name} (unchanged)[/dim]")
            if streamer:
                streamer.emit_cache_hit(repo_path.name)
            continue

        # Create a closure for this repo's build
        def make_build_fn(wr=ws_repo, rp=repo_path):
            def build_fn():
                silent_out = Output(json_mode=True, quiet=True)
                if wr.custom_build_steps:
                    return _run_custom_steps(wr, rp, silent_out, dry_run)
                return _build_single_repo(rp, silent_out, dry_run, docker)
            return build_fn

        tasks.append((repo_path.name, repo_path, make_build_fn()))

    if not tasks:
        return []

    repo_results = build_repos_parallel(tasks)

    # Flatten and report
    from .executor import ExecutionResult
    all_results: list[ExecutionResult] = []
    for rr in repo_results:
        status = "[green]✓[/green]" if rr.success else "[red]✗[/red]"
        out.info(f"  {status} {rr.repo_name} [dim]({rr.duration_s:.1f}s)[/dim]")
        all_results.extend(rr.results)

        # Record in cache
        if cache:
            ws_repo = next((r for r in repos_to_build if Path(r.path).name == rr.repo_name), None)
            if ws_repo:
                cache.record_build(
                    Path(rr.repo_path),
                    ws_repo.detected_ecosystem,
                    rr.success,
                )

    return all_results


def _resolve_build_order(repos: list[WorkspaceRepo], ws: Workspace) -> list[WorkspaceRepo]:
    """Resolve build order based on depends_on graph."""
    has_deps = any(r.depends_on for r in repos)
    if not has_deps:
        return repos

    from .graph import build_dep_graph

    graph_input = [(r.path, r.depends_on) for r in repos]
    graph = build_dep_graph(graph_input)

    try:
        ordered_names = graph.topological_sort()
    except ValueError:
        # Cycle detected — fall back to original order
        return repos

    name_to_repo = {Path(r.path).name: r for r in repos}
    ordered = [name_to_repo[n] for n in ordered_names if n in name_to_repo]

    # Add any repos not in the graph (shouldn't happen, but safety)
    seen = {Path(r.path).name for r in ordered}
    for r in repos:
        if Path(r.path).name not in seen:
            ordered.append(r)

    return ordered


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
