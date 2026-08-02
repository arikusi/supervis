"""Tests for the config-file failure modes: broken TOML and credential permissions."""

import stat

from supervisor import config as cfg


class TestBrokenToml:
    def test_invalid_toml_warns_instead_of_failing_silently(self, tmp_path, capsys):
        bad = tmp_path / "config.toml"
        bad.write_text('model = "unclosed\n')

        assert cfg._read_toml(bad) == {}
        err = capsys.readouterr().err
        assert "invalid TOML" in err
        assert str(bad) in err

    def test_missing_file_is_silent(self, tmp_path, capsys):
        assert cfg._read_toml(tmp_path / "nope.toml") == {}
        assert capsys.readouterr().err == ""

    def test_unreadable_file_warns(self, tmp_path, capsys):
        blocked = tmp_path / "config.toml"
        blocked.write_text('model = "x"\n')
        blocked.chmod(0o000)
        try:
            assert cfg._read_toml(blocked) == {}
            assert str(blocked) in capsys.readouterr().err
        finally:
            blocked.chmod(0o600)

    def test_broken_project_config_leaves_defaults_intact(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(cfg, "_OLD_CONFIG_FILE", tmp_path / "absent-old")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("SUPERVIS_MODEL", raising=False)

        project = tmp_path / "proj"
        (project / ".supervis").mkdir(parents=True)
        (project / ".supervis" / "config.toml").write_text("max_cost = [broken\n")

        c = cfg.load_config(str(project))
        assert c.model == "deepseek-v4-flash"
        assert c.max_cost is None
        assert "invalid TOML" in capsys.readouterr().err


class TestSecretPermissions:
    def test_secret_file_is_never_world_readable(self, tmp_path):
        target = tmp_path / "nested" / "config.toml"
        cfg._write_secret(target, 'api_key = "sk-test"\n')

        assert target.read_text() == 'api_key = "sk-test"\n'
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600, f"expected 0600, got {mode:o}"

    def test_rewrite_tightens_an_existing_loose_file(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text("old\n")
        target.chmod(0o644)

        cfg._write_secret(target, 'api_key = "sk-new"\n')

        assert target.read_text() == 'api_key = "sk-new"\n'
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_prompt_api_key_saves_with_tight_permissions(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "config.toml"
        monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", target)
        monkeypatch.setattr("builtins.input", lambda *_: "  sk-typed-in  ")

        assert cfg.prompt_api_key() == "sk-typed-in"
        assert 'api_key = "sk-typed-in"' in target.read_text()
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        capsys.readouterr()
