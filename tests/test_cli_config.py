# tests/test_cli_config.py
import sys
import pytest
from unittest.mock import patch, MagicMock


def _parse_run_args(args: list[str]):
    """Helper: parse 'run' subcommand args."""
    import hi_agent.cli as cli_module
    parser = cli_module.build_parser()
    return parser.parse_args(["run"] + args)


def test_run_accepts_profile_flag():
    args = _parse_run_args(["--goal", "test", "--profile", "prod"])
    assert args.profile == "prod"


def test_run_accepts_config_flag():
    args = _parse_run_args(["--goal", "test", "--config", "/path/to/config.json"])
    assert args.config == "/path/to/config.json"


def test_run_accepts_config_patch_flag():
    args = _parse_run_args(["--goal", "test", "--config-patch", '{"max_stages": 5}'])
    assert args.config_patch == '{"max_stages": 5}'


def test_run_config_patch_defaults_to_none():
    args = _parse_run_args(["--goal", "test"])
    assert args.config_patch is None
    assert args.profile is None
    assert args.config is None
