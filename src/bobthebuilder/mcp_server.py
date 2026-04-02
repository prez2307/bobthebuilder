"""MCP server - expose bob commands as Model Context Protocol tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def create_mcp_server():
    """Create an MCP server exposing bob tools.

    Implements the MCP (Model Context Protocol) stdio transport.
    AI agents connect to bob as a tool server and call bob.build(),
    bob.run(), bob.test(), bob.doctor() etc. as tool calls.
    """
    return BobMCPServer()


class BobMCPServer:
    """Minimal MCP server using stdio JSON-RPC transport."""

    TOOLS = {
        "bob_init": {
            "description": "Initialize a workspace from local paths or git URLs",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repos": {"type": "array", "items": {"type": "string"}, "description": "Paths or git URLs"},
                    "directory": {"type": "string", "description": "Working directory"},
                },
            },
        },
        "bob_build": {
            "description": "Set up project dependencies and build. Returns structured results.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Specific repo to build (optional)"},
                    "directory": {"type": "string", "description": "Working directory"},
                    "docker": {"type": "boolean", "description": "Include Docker Compose"},
                    "incremental": {"type": "boolean", "description": "Skip unchanged repos"},
                },
            },
        },
        "bob_run": {
            "description": "Detect and show the run command for a project (dry-run).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Specific repo to run"},
                    "directory": {"type": "string", "description": "Working directory"},
                },
            },
        },
        "bob_test": {
            "description": "Detect and run tests for a project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Specific repo to test"},
                    "directory": {"type": "string", "description": "Working directory"},
                },
            },
        },
        "bob_doctor": {
            "description": "Check tool versions and environment health.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Working directory"},
                },
            },
        },
        "bob_status": {
            "description": "Show workspace status and detected ecosystems.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Working directory"},
                },
            },
        },
        "bob_clean": {
            "description": "Remove build artifacts and dependency caches.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Working directory"},
                    "dry_run": {"type": "boolean", "description": "Preview without deleting"},
                },
            },
        },
    }

    def handle_request(self, request: dict) -> dict:
        """Handle a JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return self._response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "bobthebuilder",
                    "version": "0.1.0",
                },
            })

        if method == "notifications/initialized":
            return {}  # no response needed for notifications

        if method == "tools/list":
            tools = [
                {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
                for name, spec in self.TOOLS.items()
            ]
            return self._response(req_id, {"tools": tools})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            return self._handle_tool_call(req_id, tool_name, arguments)

        return self._error(req_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(self, req_id: Any, tool_name: str, args: dict) -> dict:
        """Execute a tool call."""
        directory = args.get("directory", ".")
        cwd = Path(directory).resolve()

        try:
            if tool_name == "bob_build":
                result = self._do_build(cwd, args)
            elif tool_name == "bob_run":
                result = self._do_run(cwd, args)
            elif tool_name == "bob_test":
                result = self._do_test(cwd, args)
            elif tool_name == "bob_doctor":
                result = self._do_doctor(cwd, args)
            elif tool_name == "bob_status":
                result = self._do_status(cwd)
            elif tool_name == "bob_clean":
                result = self._do_clean(cwd, args)
            elif tool_name == "bob_init":
                result = self._do_init(cwd, args)
            else:
                return self._error(req_id, -32602, f"Unknown tool: {tool_name}")

            return self._response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            })
        except Exception as e:
            return self._response(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True,
            })

    def _do_build(self, cwd: Path, args: dict) -> dict:
        """Execute bob build and return structured results."""
        import time

        from .detector import detect_project
        from .executor import execute_step
        from .strategies import get_steps_for_context
        from .workspace import load_workspace

        bob_yaml = self._find_bob_yaml(cwd)
        docker = args.get("docker", False)
        repo_filter = args.get("repo")

        all_results = []
        total_start = time.monotonic()

        if bob_yaml:
            ws = load_workspace(bob_yaml)
            ws_root = bob_yaml.parent
            repos = ws.repos
            if repo_filter:
                repos = [r for r in repos if repo_filter in r.path]

            for ws_repo in repos:
                repo_path = (ws_root / ws_repo.path).resolve()
                if repo_path.is_dir():
                    ctx = detect_project(repo_path)
                    steps = get_steps_for_context(ctx, docker_flag=docker)
                    for step in steps:
                        result = execute_step(step, cwd=step.working_dir or str(repo_path))
                        all_results.append(result.to_dict())
                        if not result.success:
                            break
        else:
            ctx = detect_project(cwd)
            steps = get_steps_for_context(ctx, docker_flag=docker)
            for step in steps:
                result = execute_step(step, cwd=step.working_dir or str(cwd))
                all_results.append(result.to_dict())
                if not result.success:
                    break

        total_duration = time.monotonic() - total_start
        return {
            "success": all(r["success"] for r in all_results),
            "total_duration_s": round(total_duration, 2),
            "steps": all_results,
        }

    def _do_run(self, cwd: Path, args: dict) -> dict:
        """Detect run command (dry-run mode for MCP)."""
        from .runner import detect_run_command

        target = cwd
        repo_filter = args.get("repo")

        if repo_filter:
            bob_yaml = self._find_bob_yaml(cwd)
            if bob_yaml:
                from .workspace import load_workspace
                ws = load_workspace(bob_yaml)
                for r in ws.repos:
                    if repo_filter in r.path:
                        target = (bob_yaml.parent / r.path).resolve()
                        break

        config = detect_run_command(target)
        if config:
            return config.to_dict()
        return {"error": f"No run command detected for {target.name}"}

    def _do_test(self, cwd: Path, args: dict) -> dict:
        """Detect test command."""
        from .tester import detect_test_command

        target = cwd
        repo_filter = args.get("repo")

        if repo_filter:
            bob_yaml = self._find_bob_yaml(cwd)
            if bob_yaml:
                from .workspace import load_workspace
                ws = load_workspace(bob_yaml)
                for r in ws.repos:
                    if repo_filter in r.path:
                        target = (bob_yaml.parent / r.path).resolve()
                        break

        config = detect_test_command(target)
        if config:
            return config.to_dict()
        return {"error": f"No test command detected for {target.name}"}

    def _do_doctor(self, cwd: Path, args: dict) -> dict:
        """Run doctor checks."""
        from .doctor import check_repo
        from .workspace import load_workspace

        bob_yaml = self._find_bob_yaml(cwd)
        results = []

        if bob_yaml:
            ws = load_workspace(bob_yaml)
            ws_root = bob_yaml.parent
            for r in ws.repos:
                repo_path = (ws_root / r.path).resolve()
                if repo_path.is_dir():
                    results.append(check_repo(repo_path).to_dict())
        else:
            results.append(check_repo(cwd).to_dict())

        return {"results": results, "healthy": all(r["healthy"] for r in results)}

    def _do_status(self, cwd: Path) -> dict:
        """Get workspace status."""
        from .detector import detect_project
        from .workspace import load_workspace

        bob_yaml = self._find_bob_yaml(cwd)
        if bob_yaml:
            ws = load_workspace(bob_yaml)
            return ws.to_dict()

        ctx = detect_project(cwd)
        return {
            "ecosystems": [e.value for e in ctx.ecosystems],
            "root": str(cwd),
        }

    def _do_clean(self, cwd: Path, args: dict) -> dict:
        """Clean build artifacts."""
        from .cleaner import clean_project, find_cleanable_dirs

        dry_run = args.get("dry_run", True)
        dirs = find_cleanable_dirs(cwd)

        result = {"dirs": [str(d) for d in dirs], "count": len(dirs), "dry_run": dry_run}
        if not dry_run:
            clean_result = clean_project(cwd, dry_run=False)
            result["removed"] = clean_result.dirs_removed
            result["bytes_freed"] = clean_result.bytes_freed
        return result

    def _do_init(self, cwd: Path, args: dict) -> dict:
        """Initialize workspace."""
        from .workspace import create_workspace

        repos = args.get("repos", [])
        repo_paths = [Path(r).resolve() for r in repos if Path(r).resolve().is_dir()]

        ws = create_workspace(cwd, repo_paths=repo_paths)
        bob_yaml = cwd / "bob.yaml"
        ws.save(bob_yaml)
        return {"workspace": ws.to_dict(), "config_path": str(bob_yaml)}

    def _find_bob_yaml(self, start: Path) -> Path | None:
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

    def _response(self, req_id: Any, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def run_stdio(self) -> None:
        """Run the MCP server on stdin/stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                error = self._error(None, -32700, "Parse error")
                sys.stdout.write(json.dumps(error) + "\n")
                sys.stdout.flush()
