"""Hooks - pre/post build hooks from bob.yaml."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .executor import ExecutionResult, validate_command


@dataclass
class HookConfig:
    """Hook configuration from bob.yaml."""

    pre_build: list[str] | None = None
    post_build: list[str] | None = None
    pre_run: list[str] | None = None
    post_run: list[str] | None = None
    pre_test: list[str] | None = None
    post_test: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> HookConfig:
        if not data:
            return cls()
        return cls(
            pre_build=_parse_hook(data.get("pre_build")),
            post_build=_parse_hook(data.get("post_build")),
            pre_run=_parse_hook(data.get("pre_run")),
            post_run=_parse_hook(data.get("post_run")),
            pre_test=_parse_hook(data.get("pre_test")),
            post_test=_parse_hook(data.get("post_test")),
        )

    def to_dict(self) -> dict:
        d: dict = {}
        if self.pre_build:
            d["pre_build"] = " ".join(self.pre_build)
        if self.post_build:
            d["post_build"] = " ".join(self.post_build)
        if self.pre_run:
            d["pre_run"] = " ".join(self.pre_run)
        if self.post_run:
            d["post_run"] = " ".join(self.post_run)
        if self.pre_test:
            d["pre_test"] = " ".join(self.pre_test)
        if self.post_test:
            d["post_test"] = " ".join(self.post_test)
        return d

    def get_hooks(self, phase: str) -> tuple[list[str] | None, list[str] | None]:
        """Get pre and post hooks for a phase (build, run, test)."""
        pre = getattr(self, f"pre_{phase}", None)
        post = getattr(self, f"post_{phase}", None)
        return pre, post


def _parse_hook(value: str | list | None) -> list[str] | None:
    """Parse a hook value into a command list."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return value.split()
    return None


def run_hook(
    name: str,
    command: list[str],
    cwd: str,
    dry_run: bool = False,
) -> ExecutionResult:
    """Run a single hook command."""
    if not validate_command(command):
        return ExecutionResult(
            step_name=name,
            success=False,
            error=f"Hook command blocked by safety filter: {command}",
            command=command,
        )

    if dry_run:
        return ExecutionResult(
            step_name=name,
            success=True,
            command=command,
        )

    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=name,
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_s=duration,
            command=command,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=name,
            success=False,
            exit_code=-1,
            error="Hook timed out after 120 seconds",
            duration_s=duration,
            command=command,
        )
    except FileNotFoundError:
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=name,
            success=False,
            exit_code=-1,
            error=f"Command not found: {command[0]}",
            duration_s=duration,
            command=command,
        )
