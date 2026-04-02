"""Tests for MCP server."""

import json
from pathlib import Path

import pytest

from bobthebuilder.mcp_server import BobMCPServer


@pytest.fixture
def server():
    return BobMCPServer()


@pytest.fixture
def tmp_project(tmp_path):
    def _create(files: dict[str, str | None] = None):
        files = files or {}
        for name, content in files.items():
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "")
        return tmp_path
    return _create


class TestMCPProtocol:
    def test_initialize(self, server):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["serverInfo"]["name"] == "bobthebuilder"

    def test_tools_list(self, server):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        tools = response["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "bob_build" in tool_names
        assert "bob_run" in tool_names
        assert "bob_test" in tool_names
        assert "bob_doctor" in tool_names
        assert "bob_status" in tool_names
        assert "bob_clean" in tool_names
        assert "bob_init" in tool_names

    def test_unknown_method(self, server):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "unknown/method",
            "params": {},
        })
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_notifications_initialized(self, server):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        assert response == {}


class TestMCPToolCalls:
    def test_bob_status(self, server, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "test"}),
            "package-lock.json": "{}",
        })
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "bob_status",
                "arguments": {"directory": str(root)},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "ecosystems" in content

    def test_bob_test_detection(self, server, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\ngo 1.21",
        })
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "bob_test",
                "arguments": {"directory": str(root)},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["command"] == ["go", "test", "./..."]

    def test_bob_run_detection(self, server, tmp_project):
        root = tmp_project({
            "Cargo.toml": '[package]\nname = "myapp"',
        })
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "bob_run",
                "arguments": {"directory": str(root)},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["command"] == ["cargo", "run"]

    def test_bob_doctor(self, server, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\ngo 1.21",
        })
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "bob_doctor",
                "arguments": {"directory": str(root)},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "results" in content
        assert "healthy" in content

    def test_bob_clean_dry_run(self, server, tmp_project):
        root = tmp_project({
            "package.json": "{}",
        })
        # Create a node_modules dir
        (root / "node_modules" / "foo").mkdir(parents=True)
        (root / "node_modules" / "foo" / "index.js").write_text("hi")

        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "bob_clean",
                "arguments": {"directory": str(root), "dry_run": True},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["count"] >= 1
        assert content["dry_run"] is True

    def test_unknown_tool(self, server):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "bob_nonexistent",
                "arguments": {},
            },
        })
        assert "error" in response

    def test_bob_init(self, server, tmp_project):
        root = tmp_project({
            "myrepo/package.json": json.dumps({"name": "test"}),
        })
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "bob_init",
                "arguments": {"directory": str(root), "repos": [str(root / "myrepo")]},
            },
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "workspace" in content
        assert "config_path" in content


class TestMCPToolSchema:
    def test_all_tools_have_schemas(self, server):
        for name, spec in server.TOOLS.items():
            assert "description" in spec, f"{name} missing description"
            assert "inputSchema" in spec, f"{name} missing inputSchema"
            assert spec["inputSchema"]["type"] == "object"
