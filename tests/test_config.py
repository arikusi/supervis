"""Tests for supervisor.config module — TOML config system."""

from supervisor.config import (
    Config,
    _apply_env,
    _apply_toml,
    _read_toml,
    load_config,
    load_project_instructions,
)


class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.model == "deepseek-chat"
        assert c.thinking is True
        assert c.max_cost is None
        assert c.shell_timeout == 15
        assert c.claude_timeout == 300


class TestApplyToml:
    def test_flat_keys(self):
        c = Config()
        _apply_toml(c, {"api_key": "sk-test", "model": "deepseek-reasoner", "thinking": False})
        assert c.api_key == "sk-test"
        assert c.model == "deepseek-reasoner"
        assert c.thinking is False

    def test_behavior_section(self):
        c = Config()
        _apply_toml(c, {"behavior": {"max_cost": 2.5, "shell_timeout": 30}})
        assert c.max_cost == 2.5
        assert c.shell_timeout == 30

    def test_flat_behavior_keys(self):
        c = Config()
        _apply_toml(c, {"shell_timeout": 20, "truncation_limit": 8000})
        assert c.shell_timeout == 20
        assert c.truncation_limit == 8000

    def test_strips_whitespace(self):
        c = Config()
        _apply_toml(c, {"api_key": "  sk-test  ", "model": "  deepseek-chat  "})
        assert c.api_key == "sk-test"
        assert c.model == "deepseek-chat"


class TestApplyEnv:
    def test_deepseek_api_key(self, monkeypatch):
        c = Config()
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
        _apply_env(c)
        assert c.api_key == "sk-env"

    def test_supervis_model(self, monkeypatch):
        c = Config()
        monkeypatch.setenv("SUPERVIS_MODEL", "deepseek-reasoner")
        _apply_env(c)
        assert c.model == "deepseek-reasoner"

    def test_supervis_thinking_off(self, monkeypatch):
        c = Config()
        monkeypatch.setenv("SUPERVIS_THINKING", "false")
        _apply_env(c)
        assert c.thinking is False

    def test_empty_env_ignored(self, monkeypatch):
        c = Config(api_key="original")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        _apply_env(c)
        assert c.api_key == "original"


class TestReadToml:
    def test_reads_valid_toml(self, tmp_path):
        f = tmp_path / "config.toml"
        f.write_text('api_key = "sk-test"\nmodel = "deepseek-chat"\n')
        data = _read_toml(f)
        assert data["api_key"] == "sk-test"

    def test_missing_file(self, tmp_path):
        data = _read_toml(tmp_path / "nonexistent.toml")
        assert data == {}

    def test_invalid_toml(self, tmp_path):
        f = tmp_path / "bad.toml"
        f.write_text("this is not [valid toml")
        data = _read_toml(f)
        assert data == {}


class TestLoadConfig:
    def test_global_config(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "supervis"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('api_key = "sk-global"\nmodel = "deepseek-reasoner"\n')

        monkeypatch.setattr("supervisor.config._GLOBAL_CONFIG_FILE", config_dir / "config.toml")
        monkeypatch.setattr("supervisor.config._OLD_CONFIG_FILE", config_dir / "old_config")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("SUPERVIS_MODEL", raising=False)
        monkeypatch.delenv("SUPERVIS_THINKING", raising=False)

        config = load_config()
        assert config.api_key == "sk-global"
        assert config.model == "deepseek-reasoner"

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "supervis"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('api_key = "sk-global"\nmodel = "deepseek-chat"\n')

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / ".supervis").mkdir()
        (project_dir / ".supervis" / "config.toml").write_text('model = "deepseek-reasoner"\nthinking = false\n')

        monkeypatch.setattr("supervisor.config._GLOBAL_CONFIG_FILE", config_dir / "config.toml")
        monkeypatch.setattr("supervisor.config._OLD_CONFIG_FILE", config_dir / "old_config")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("SUPERVIS_MODEL", raising=False)
        monkeypatch.delenv("SUPERVIS_THINKING", raising=False)

        config = load_config(str(project_dir))
        assert config.api_key == "sk-global"
        assert config.model == "deepseek-reasoner"
        assert config.thinking is False

    def test_env_overrides_all(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "supervis"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('api_key = "sk-global"\n')

        monkeypatch.setattr("supervisor.config._GLOBAL_CONFIG_FILE", config_dir / "config.toml")
        monkeypatch.setattr("supervisor.config._OLD_CONFIG_FILE", config_dir / "old_config")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")

        config = load_config()
        assert config.api_key == "sk-env"


class TestMigration:
    def test_migrates_old_format(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "supervis"
        config_dir.mkdir(parents=True)
        (config_dir / "config").write_text("DEEPSEEK_API_KEY=sk-old\n")

        monkeypatch.setattr("supervisor.config._GLOBAL_CONFIG_DIR", config_dir)
        monkeypatch.setattr("supervisor.config._GLOBAL_CONFIG_FILE", config_dir / "config.toml")
        monkeypatch.setattr("supervisor.config._OLD_CONFIG_FILE", config_dir / "config")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("SUPERVIS_MODEL", raising=False)
        monkeypatch.delenv("SUPERVIS_THINKING", raising=False)

        config = load_config()
        assert config.api_key == "sk-old"
        assert (config_dir / "config.toml").exists()
        assert (config_dir / "config").exists()  # old file not deleted


class TestLoadProjectInstructions:
    def test_returns_content_when_file_exists(self, tmp_path):
        d = tmp_path / ".supervis"
        d.mkdir()
        (d / "SUPERVIS.md").write_text("Use TypeScript.\n")
        assert load_project_instructions(str(tmp_path)) == "Use TypeScript."

    def test_returns_none_when_no_directory(self, tmp_path):
        assert load_project_instructions(str(tmp_path)) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        (tmp_path / ".supervis").mkdir()
        assert load_project_instructions(str(tmp_path)) is None

    def test_returns_none_when_file_empty(self, tmp_path):
        d = tmp_path / ".supervis"
        d.mkdir()
        (d / "SUPERVIS.md").write_text("")
        assert load_project_instructions(str(tmp_path)) is None

    def test_strips_whitespace(self, tmp_path):
        d = tmp_path / ".supervis"
        d.mkdir()
        (d / "SUPERVIS.md").write_text("  hello  \n\n")
        assert load_project_instructions(str(tmp_path)) == "hello"
