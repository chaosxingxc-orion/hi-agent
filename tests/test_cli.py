"""Tests for CLI argument parsing (hi_agent.cli.build_parser)."""

from __future__ import annotations

import argparse
import io
import urllib.error

import pytest

from hi_agent.cli import _api_request, _cmd_run, build_parser


@pytest.fixture()
def parser():
    return build_parser()


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_parse_run_with_goal(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "Analyze data"])
        assert args.command == "run"
        assert args.goal == "Analyze data"

    def test_run_default_task_family(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "x"])
        assert args.task_family == "quick_task"

    def test_run_default_risk_level(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "x"])
        assert args.risk_level == "low"

    def test_run_custom_task_family(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "x", "--task-family", "complex"])
        assert args.task_family == "complex"

    def test_run_json_flag(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "x", "--json"])
        assert args.json is True

    def test_run_local_flag(self, parser) -> None:
        args = parser.parse_args(["run", "--goal", "x", "--local"])
        assert args.local is True

    def test_run_missing_goal_raises(self, parser) -> None:
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])


# ---------------------------------------------------------------------------
# serve command
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_parse_serve_defaults(self, parser) -> None:
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 8080

    def test_serve_custom_port(self, parser) -> None:
        args = parser.parse_args(["serve", "--port", "9090"])
        assert args.port == 9090

    def test_serve_custom_host(self, parser) -> None:
        args = parser.parse_args(["serve", "--host", "127.0.0.1"])
        assert args.host == "127.0.0.1"


# ---------------------------------------------------------------------------
# resume command
# ---------------------------------------------------------------------------


class TestResumeCommand:
    def test_parse_resume_checkpoint(self, parser) -> None:
        args = parser.parse_args(["resume", "--checkpoint", "cp.json"])
        assert args.command == "resume"
        assert args.checkpoint == "cp.json"

    def test_resume_run_id(self, parser) -> None:
        args = parser.parse_args(["resume", "--run-id", "run-42"])
        assert args.run_id == "run-42"

    def test_resume_json_flag(self, parser) -> None:
        args = parser.parse_args(["resume", "--checkpoint", "cp.json", "--json"])
        assert args.json is True


# ---------------------------------------------------------------------------
# global options
# ---------------------------------------------------------------------------


class TestGlobalOptions:
    def test_default_api_host(self, parser) -> None:
        args = parser.parse_args(["health"])
        assert args.api_host == "127.0.0.1"

    def test_default_api_port(self, parser) -> None:
        args = parser.parse_args(["health"])
        assert args.api_port == 8080

    def test_custom_api_host(self, parser) -> None:
        args = parser.parse_args(["--api-host", "10.0.0.1", "health"])
        assert args.api_host == "10.0.0.1"

    def test_custom_api_port(self, parser) -> None:
        args = parser.parse_args(["--api-port", "3000", "health"])
        assert args.api_port == 3000

    def test_status_command(self, parser) -> None:
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_health_command(self, parser) -> None:
        args = parser.parse_args(["health"])
        assert args.command == "health"

    def test_no_command_gives_none(self, parser) -> None:
        args = parser.parse_args([])
        assert args.command is None


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestApiRequestDecoding:
    def test_http_error_with_non_json_body_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        err = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/runs",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"<html>500 server error</html>"),
        )

        def _raise_http_error(_req, timeout=None):
            raise err

        monkeypatch.setattr("hi_agent.cli.urllib.request.urlopen", _raise_http_error)

        status, data = _api_request("POST", "http://127.0.0.1:8080/runs", {"goal": "x"})
        assert status == 500
        assert data["error"] in {"http_error", "non_json_response"}
        assert "status_code" in data

    def test_success_with_non_json_body_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_resp = _FakeResponse(200, b"plain text ok")
        monkeypatch.setattr(
            "hi_agent.cli.urllib.request.urlopen",
            lambda _req, timeout=None: fake_resp,
        )

        status, data = _api_request("GET", "http://127.0.0.1:8080/health")
        assert status == 200
        assert data["error"] == "non_json_response"
        assert "raw_body" in data

    def test_empty_body_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_resp = _FakeResponse(204, b"")
        monkeypatch.setattr(
            "hi_agent.cli.urllib.request.urlopen",
            lambda _req, timeout=None: fake_resp,
        )

        status, data = _api_request("GET", "http://127.0.0.1:8080/runs")
        assert status == 204
        assert data["error"] == "empty_response_body"

    def test_api_request_passes_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, float] = {}

        def _fake_urlopen(_req, timeout=None):
            captured["timeout"] = timeout
            return _FakeResponse(200, b"{}")

        monkeypatch.setattr("hi_agent.cli.urllib.request.urlopen", _fake_urlopen)

        status, _ = _api_request(
            "GET",
            "http://127.0.0.1:8080/health",
            timeout_seconds=3.5,
        )
        assert status == 200
        assert captured["timeout"] == 3.5

    @pytest.mark.parametrize("env_value", ["abc", "0", "-1"])
    def test_api_request_invalid_env_timeout_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_value: str,
    ) -> None:
        captured: dict[str, float] = {}

        def _fake_urlopen(_req, timeout=None):
            captured["timeout"] = timeout
            return _FakeResponse(200, b"{}")

        monkeypatch.setenv("HI_AGENT_API_TIMEOUT_SECONDS", env_value)
        monkeypatch.setattr("hi_agent.cli.urllib.request.urlopen", _fake_urlopen)

        status, _ = _api_request("GET", "http://127.0.0.1:8080/health")
        assert status == 200
        assert captured["timeout"] == 15.0

    def test_api_request_invalid_env_timeout_logs_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("HI_AGENT_API_TIMEOUT_SECONDS", "not-a-number")

        def _fake_urlopen(_req, timeout=None):
            return _FakeResponse(200, b"{}")

        monkeypatch.setattr("hi_agent.cli.urllib.request.urlopen", _fake_urlopen)

        status, _ = _api_request("GET", "http://127.0.0.1:8080/health")
        assert status == 200
        err = capsys.readouterr().err
        assert "HI_AGENT_API_TIMEOUT_SECONDS" in err
        assert "not-a-number" in err


class TestRunCommandExecution:
    def test_cmd_run_json_exits_nonzero_on_remote_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (502, {"error": "bad_gateway"}),
        )
        args = argparse.Namespace(
            local=False,
            goal="x",
            task_family="quick_task",
            risk_level="low",
            json=True,
            api_host="127.0.0.1",
            api_port=8080,
        )
        with pytest.raises(SystemExit) as exc:
            _cmd_run(args)
        assert exc.value.code == 1
        output = capsys.readouterr().out
        assert "bad_gateway" in output


class TestStatusHealthCommands:
    @pytest.mark.parametrize("command", ["status", "health"])
    def test_status_and_health_have_json_flag(
        self, parser: argparse.ArgumentParser, command: str
    ) -> None:
        args = parser.parse_args([command, "--json"])
        assert args.json is True

    def test_status_defaults_to_text_mode(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (200, {"run_id": "run-1", "state": "done"}),
        )
        args = argparse.Namespace(
            api_host="127.0.0.1",
            api_port=8080,
            run_id="run-1",
            json=False,
        )

        from hi_agent.cli import _cmd_status

        _cmd_status(args)
        out = capsys.readouterr().out
        assert "run-1" in out
        assert not out.lstrip().startswith("{")

    def test_status_json_outputs_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (200, {"run_id": "run-1", "state": "done"}),
        )
        args = argparse.Namespace(
            api_host="127.0.0.1",
            api_port=8080,
            run_id="run-1",
            json=True,
        )

        from hi_agent.cli import _cmd_status

        _cmd_status(args)
        out = capsys.readouterr().out
        assert '"run_id": "run-1"' in out
        assert out.lstrip().startswith("{")

    def test_health_defaults_to_text_mode(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (200, {"status": "ok"}),
        )
        args = argparse.Namespace(api_host="127.0.0.1", api_port=8080, json=False)

        from hi_agent.cli import _cmd_health

        _cmd_health(args)
        out = capsys.readouterr().out
        assert "ok" in out
        assert not out.lstrip().startswith("{")

    def test_health_json_outputs_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (200, {"status": "ok"}),
        )
        args = argparse.Namespace(api_host="127.0.0.1", api_port=8080, json=True)

        from hi_agent.cli import _cmd_health

        _cmd_health(args)
        out = capsys.readouterr().out
        assert '"status": "ok"' in out
        assert out.lstrip().startswith("{")

    def test_health_non_200_exits_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "hi_agent.cli._api_request",
            lambda *_args, **_kwargs: (503, {"error": "unavailable"}),
        )
        args = argparse.Namespace(api_host="127.0.0.1", api_port=8080, json=True)

        from hi_agent.cli import _cmd_health

        with pytest.raises(SystemExit) as exc:
            _cmd_health(args)
        assert exc.value.code == 1
        assert '"error": "unavailable"' in capsys.readouterr().out
