"""Output formatting - human-readable (Rich) and JSON modes."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from .executor import ExecutionResult
    from .models import BuildPlan, BuildStep, ProjectContext
    from .workspace import Workspace

console = Console()
err_console = Console(stderr=True)


class Output:
    """Base output handler."""

    def __init__(self, json_mode: bool = False, quiet: bool = False):
        self.json_mode = json_mode
        self.quiet = quiet

    def detected(self, repos: list[tuple[str, str, str | None]]) -> None:
        """Show what was detected. repos = [(path, ecosystem, package_manager)]"""
        if self.quiet:
            return
        if self.json_mode:
            return  # JSON output is emitted at the end

        console.print()
        table = Table(title="Detected Projects", show_header=True)
        table.add_column("Path", style="cyan")
        table.add_column("Ecosystem", style="green")
        table.add_column("Tool", style="yellow")
        for path, eco, pm in repos:
            table.add_row(path, eco, pm or "-")
        console.print(table)
        console.print()

    def plan(self, steps: list[BuildStep]) -> None:
        """Show the build plan."""
        if self.quiet or self.json_mode:
            return
        console.print("[bold]Plan:[/bold]")
        for i, step in enumerate(steps, 1):
            cmd = " ".join(step.command)
            risk = f" [yellow]({step.risk_level.value} risk)[/yellow]" if step.risk_level.value != "low" else ""
            console.print(f"  {i}. {step.description} [dim]({cmd})[/dim]{risk}")
        console.print()

    def step_start(self, step: BuildStep) -> None:
        if self.quiet or self.json_mode:
            return
        cmd = " ".join(step.command)
        console.print(f"  [bold blue]>[/bold blue] {step.description} [dim]({cmd})[/dim]")

    def step_done(self, result: ExecutionResult) -> None:
        if self.quiet or self.json_mode:
            return
        if result.success:
            console.print(
                f"  [bold green]✓[/bold green] {result.step_name} [dim]({result.duration_s:.1f}s)[/dim]"
            )
        else:
            console.print(f"  [bold red]✗[/bold red] {result.step_name}")
            if result.error:
                console.print(f"    [red]{result.error}[/red]")
            if result.stderr:
                for line in result.stderr.strip().splitlines()[:5]:
                    console.print(f"    [dim]{line}[/dim]")

    def summary(self, results: list[ExecutionResult], total_duration: float) -> None:
        """Final summary."""
        if self.json_mode:
            output = {
                "success": all(r.success for r in results),
                "total_duration_s": round(total_duration, 2),
                "steps": [r.to_dict() for r in results],
            }
            print(json.dumps(output, indent=2))
            return

        if self.quiet:
            if not all(r.success for r in results):
                err_console.print("[red]Build failed[/red]")
                sys.exit(1)
            return

        console.print()
        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        if failed == 0:
            console.print(
                Panel(
                    f"[bold green]Project ready![/bold green] "
                    f"{succeeded} steps completed in {total_duration:.1f}s",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold red]Build failed.[/bold red] "
                    f"{succeeded} succeeded, {failed} failed in {total_duration:.1f}s",
                    border_style="red",
                )
            )

    def workspace_created(self, ws: Workspace, path: str) -> None:
        if self.json_mode:
            print(json.dumps({"workspace": ws.to_dict(), "config_path": path}, indent=2))
            return
        if self.quiet:
            return
        console.print(f"[bold green]Workspace created:[/bold green] {path}")

    def error(self, msg: str) -> None:
        if self.json_mode:
            print(json.dumps({"success": False, "error": msg}))
        else:
            err_console.print(f"[bold red]Error:[/bold red] {msg}")

    def info(self, msg: str) -> None:
        if not self.quiet and not self.json_mode:
            console.print(msg)
