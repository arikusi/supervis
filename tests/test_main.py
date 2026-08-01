"""Tests for supervisor.main — argument parsing and startup preflight."""

from unittest.mock import patch

import pytest

from supervisor import __version__
from supervisor.main import build_parser, main


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "supervis" in out
    assert "--debug" in out


def test_project_dir_defaults_to_none():
    args = build_parser().parse_args([])
    assert args.project_dir is None
    assert args.debug is False


def test_project_dir_and_debug_parse_together():
    args = build_parser().parse_args(["/tmp", "--debug"])
    assert args.project_dir == "/tmp"
    assert args.debug is True


def test_missing_directory_exits_one(capsys, tmp_path):
    missing = str(tmp_path / "nope")
    with pytest.raises(SystemExit) as exc:
        main([missing])
    assert exc.value.code == 1
    assert "Directory not found" in capsys.readouterr().err


def test_missing_claude_binary_exits_one(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (
        patch("supervisor.logging_config.setup_logging"),
        patch("supervisor.claude.shutil.which", return_value=None),
        pytest.raises(SystemExit) as exc,
    ):
        main([str(tmp_path)])
    assert exc.value.code == 1
    assert "Claude Code CLI not found" in capsys.readouterr().err
