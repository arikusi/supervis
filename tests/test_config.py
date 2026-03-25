"""Tests for supervisor.config module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from supervisor.config import get_api_key, load_project_instructions


class TestGetApiKey:
    def test_env_var_takes_precedence(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-from-env"}):
            assert get_api_key() == "sk-from-env"

    def test_env_var_stripped(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "  sk-padded  "}):
            assert get_api_key() == "sk-padded"

    def test_falls_back_to_config_file(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with patch("supervisor.config._read_saved", return_value="sk-from-file"):
                assert get_api_key() == "sk-from-file"

    def test_empty_env_var_falls_through(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "  "}):
            with patch("supervisor.config._read_saved", return_value="sk-from-file"):
                assert get_api_key() == "sk-from-file"


class TestLoadProjectInstructions:
    def test_returns_content_when_file_exists(self, tmp_path):
        supervis_dir = tmp_path / ".supervis"
        supervis_dir.mkdir()
        (supervis_dir / "SUPERVIS.md").write_text("Use TypeScript.\nFollow PLAN.md.")
        result = load_project_instructions(str(tmp_path))
        assert result == "Use TypeScript.\nFollow PLAN.md."

    def test_returns_none_when_no_directory(self, tmp_path):
        result = load_project_instructions(str(tmp_path))
        assert result is None

    def test_returns_none_when_file_missing(self, tmp_path):
        (tmp_path / ".supervis").mkdir()
        result = load_project_instructions(str(tmp_path))
        assert result is None

    def test_returns_none_when_file_empty(self, tmp_path):
        supervis_dir = tmp_path / ".supervis"
        supervis_dir.mkdir()
        (supervis_dir / "SUPERVIS.md").write_text("")
        result = load_project_instructions(str(tmp_path))
        assert result is None

    def test_strips_whitespace(self, tmp_path):
        supervis_dir = tmp_path / ".supervis"
        supervis_dir.mkdir()
        (supervis_dir / "SUPERVIS.md").write_text("\n  content here  \n\n")
        result = load_project_instructions(str(tmp_path))
        assert result == "content here"
