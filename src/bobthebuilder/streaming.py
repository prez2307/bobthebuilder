"""Streaming JSON output - NDJSON events for AI agents."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import IO, Any


@dataclass
class StreamEvent:
    """A single NDJSON event."""

    event: str
    data: dict

    def to_json(self) -> str:
        payload = {"event": self.event, "timestamp": time.time(), **self.data}
        return json.dumps(payload)


class StreamingOutput:
    """Emits newline-delimited JSON events for real-time agent consumption.

    Usage:
        stream = StreamingOutput()
        stream.emit_build_start(repo_name="frontend", steps=3)
        stream.emit_step_start(repo="frontend", step="install-deps", command=["npm", "ci"])
        stream.emit_step_done(repo="frontend", step="install-deps", success=True, duration=3.2)
        stream.emit_build_done(repo_name="frontend", success=True, duration=4.5)
    """

    def __init__(self, output: IO[str] | None = None):
        self._output = output or sys.stdout

    def _emit(self, event: str, **data: Any) -> None:
        evt = StreamEvent(event=event, data=data)
        self._output.write(evt.to_json() + "\n")
        self._output.flush()

    # --- Workspace events ---

    def emit_workspace_start(self, workspace: str, repos: list[str]) -> None:
        self._emit("workspace_start", workspace=workspace, repos=repos)

    def emit_workspace_done(self, workspace: str, success: bool, duration_s: float) -> None:
        self._emit("workspace_done", workspace=workspace, success=success, duration_s=round(duration_s, 2))

    # --- Build events ---

    def emit_build_start(self, repo_name: str, steps: int) -> None:
        self._emit("build_start", repo=repo_name, total_steps=steps)

    def emit_build_done(self, repo_name: str, success: bool, duration_s: float) -> None:
        self._emit("build_done", repo=repo_name, success=success, duration_s=round(duration_s, 2))

    # --- Step events ---

    def emit_step_start(self, repo: str, step: str, command: list[str]) -> None:
        self._emit("step_start", repo=repo, step=step, command=command)

    def emit_step_done(
        self,
        repo: str,
        step: str,
        success: bool,
        duration_s: float,
        exit_code: int = 0,
        error: str = "",
    ) -> None:
        data: dict[str, Any] = {
            "repo": repo,
            "step": step,
            "success": success,
            "duration_s": round(duration_s, 2),
        }
        if not success:
            data["exit_code"] = exit_code
            if error:
                data["error"] = error
        self._emit("step_done", **data)

    # --- Hook events ---

    def emit_hook(self, repo: str, hook: str, success: bool, duration_s: float = 0.0) -> None:
        self._emit("hook", repo=repo, hook=hook, success=success, duration_s=round(duration_s, 2))

    # --- Cache events ---

    def emit_cache_hit(self, repo: str) -> None:
        self._emit("cache_hit", repo=repo, message="Skipped (lockfiles unchanged)")

    # --- Doctor events ---

    def emit_doctor_check(self, repo: str, tool: str, installed: bool, version: str = "") -> None:
        self._emit("doctor_check", repo=repo, tool=tool, installed=installed, version=version)

    # --- Error events ---

    def emit_error(self, message: str, repo: str = "") -> None:
        data: dict[str, str] = {"message": message}
        if repo:
            data["repo"] = repo
        self._emit("error", **data)
