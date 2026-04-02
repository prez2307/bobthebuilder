"""Tests for streaming JSON output."""

import io
import json

from bobthebuilder.streaming import StreamingOutput


class TestStreamingOutput:
    def _make_stream(self) -> tuple[StreamingOutput, io.StringIO]:
        buf = io.StringIO()
        return StreamingOutput(output=buf), buf

    def _parse_events(self, buf: io.StringIO) -> list[dict]:
        buf.seek(0)
        return [json.loads(line) for line in buf if line.strip()]

    def test_workspace_start(self):
        stream, buf = self._make_stream()
        stream.emit_workspace_start("my-ws", ["repo1", "repo2"])
        events = self._parse_events(buf)
        assert len(events) == 1
        assert events[0]["event"] == "workspace_start"
        assert events[0]["workspace"] == "my-ws"
        assert events[0]["repos"] == ["repo1", "repo2"]

    def test_workspace_done(self):
        stream, buf = self._make_stream()
        stream.emit_workspace_done("my-ws", True, 4.5)
        events = self._parse_events(buf)
        assert events[0]["event"] == "workspace_done"
        assert events[0]["success"] is True
        assert events[0]["duration_s"] == 4.5

    def test_build_lifecycle(self):
        stream, buf = self._make_stream()
        stream.emit_build_start("frontend", 3)
        stream.emit_step_start("frontend", "install", ["npm", "ci"])
        stream.emit_step_done("frontend", "install", True, 2.1)
        stream.emit_build_done("frontend", True, 2.1)
        events = self._parse_events(buf)
        assert len(events) == 4
        assert events[0]["event"] == "build_start"
        assert events[1]["event"] == "step_start"
        assert events[2]["event"] == "step_done"
        assert events[3]["event"] == "build_done"

    def test_step_failure_includes_error(self):
        stream, buf = self._make_stream()
        stream.emit_step_done("repo", "build", False, 1.0, exit_code=1, error="compile error")
        events = self._parse_events(buf)
        assert events[0]["success"] is False
        assert events[0]["exit_code"] == 1
        assert events[0]["error"] == "compile error"

    def test_cache_hit(self):
        stream, buf = self._make_stream()
        stream.emit_cache_hit("backend")
        events = self._parse_events(buf)
        assert events[0]["event"] == "cache_hit"
        assert events[0]["repo"] == "backend"

    def test_hook_event(self):
        stream, buf = self._make_stream()
        stream.emit_hook("frontend", "pre_build", True, 0.5)
        events = self._parse_events(buf)
        assert events[0]["event"] == "hook"
        assert events[0]["hook"] == "pre_build"

    def test_doctor_check(self):
        stream, buf = self._make_stream()
        stream.emit_doctor_check("myrepo", "node", True, "v20.0.0")
        events = self._parse_events(buf)
        assert events[0]["event"] == "doctor_check"
        assert events[0]["tool"] == "node"
        assert events[0]["installed"] is True

    def test_error_event(self):
        stream, buf = self._make_stream()
        stream.emit_error("Something broke", repo="backend")
        events = self._parse_events(buf)
        assert events[0]["event"] == "error"
        assert events[0]["message"] == "Something broke"

    def test_events_have_timestamps(self):
        stream, buf = self._make_stream()
        stream.emit_build_start("repo", 1)
        events = self._parse_events(buf)
        assert "timestamp" in events[0]
        assert isinstance(events[0]["timestamp"], float)

    def test_ndjson_format(self):
        """Each event is a single line of valid JSON."""
        stream, buf = self._make_stream()
        stream.emit_build_start("a", 1)
        stream.emit_build_start("b", 2)
        buf.seek(0)
        lines = buf.readlines()
        assert len(lines) == 2
        for line in lines:
            assert line.endswith("\n")
            json.loads(line)  # Should not raise
