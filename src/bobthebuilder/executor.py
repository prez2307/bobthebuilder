"""Command executor - runs build steps with safety controls."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field

from .models import BuildStep

# Allowlist of command prefixes that are safe to run
ALLOWED_COMMANDS: set[str] = {
    "npm",
    "npx",
    "yarn",
    "pnpm",
    "bun",
    "pip",
    "pip3",
    "uv",
    "poetry",
    "pipenv",
    "python",
    "python3",
    "go",
    "cargo",
    "rustup",
    "bundle",
    "gem",
    "rake",
    "make",
    "docker",
    "git",
    "node",
    "ruby",
    "cp",
    "mkdir",
    "echo",
    "ls",
    "cat",
}

# Commands that are always blocked
BLOCKED_COMMANDS: set[str] = {
    "sudo",
    "su",
    "rm",
    "curl",
    "wget",
    "bash",
    "sh",
    "eval",
    "exec",
    "chmod",
    "chown",
    "kill",
    "killall",
    "reboot",
    "shutdown",
    "poweroff",
    "dd",
    "mkfs",
    "fdisk",
}


@dataclass
class ExecutionResult:
    step_name: str
    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_s: float = 0.0
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "step": self.step_name,
            "success": self.success,
            "duration_s": round(self.duration_s, 2),
        }
        if self.command:
            d["command"] = self.command
        if not self.success:
            d["exit_code"] = self.exit_code
            if self.error:
                d["error"] = self.error
            if self.stderr:
                d["stderr"] = self.stderr[:500]  # truncate for JSON output
        return d


def validate_command(command: list[str]) -> bool:
    """Check if a command is safe to run."""
    if not command:
        return False
    binary = command[0]
    if binary in BLOCKED_COMMANDS:
        return False
    if binary in ALLOWED_COMMANDS:
        return True
    return False


def execute_step(
    step: BuildStep,
    cwd: str | None = None,
    dry_run: bool = False,
) -> ExecutionResult:
    """Execute a single build step."""
    if not validate_command(step.command):
        return ExecutionResult(
            step_name=step.name,
            success=False,
            error=f"Command blocked by safety filter: {step.command}",
            command=step.command,
        )

    if dry_run:
        return ExecutionResult(
            step_name=step.name,
            success=True,
            command=step.command,
        )

    start = time.monotonic()
    try:
        result = subprocess.run(
            step.command,
            cwd=cwd or step.working_dir,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per step
        )
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=step.name,
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_s=duration,
            command=step.command,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=step.name,
            success=False,
            exit_code=-1,
            error="Command timed out after 300 seconds",
            duration_s=duration,
            command=step.command,
        )
    except FileNotFoundError:
        duration = time.monotonic() - start
        return ExecutionResult(
            step_name=step.name,
            success=False,
            exit_code=-1,
            error=f"Command not found: {step.command[0]}",
            duration_s=duration,
            command=step.command,
        )
