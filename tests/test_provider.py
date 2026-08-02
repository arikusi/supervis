"""Tests for pointing supervis at an endpoint other than DeepSeek."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supervisor import config as cfg
from supervisor.app import SupervisApp
from supervisor.commands import dispatch
from supervisor.config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_PRO_MODEL, Config
from supervisor.deepseek import _api_call
from supervisor.pricing import clear_user_pricing, price_for
from supervisor.session import Session


@pytest.fixture(autouse=True)
def _isolate_pricing():
    clear_user_pricing()
    yield
    clear_user_pricing()


def _load(tmp_path, monkeypatch, toml: str, project_toml: str | None = None) -> Config:
    """Load config from a throwaway global file, ignoring the real environment."""
    global_file = tmp_path / "config.toml"
    global_file.write_text(toml)
    monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", global_file)
    monkeypatch.setattr(cfg, "_OLD_CONFIG_FILE", tmp_path / "absent-old")
    for var in ("DEEPSEEK_API_KEY", "SUPERVIS_API_KEY", "SUPERVIS_BASE_URL", "SUPERVIS_MODEL", "SUPERVIS_PRO_MODEL"):
        monkeypatch.delenv(var, raising=False)

    project = None
    if project_toml is not None:
        project = tmp_path / "proj"
        (project / ".supervis").mkdir(parents=True)
        (project / ".supervis" / "config.toml").write_text(project_toml)

    return cfg.load_config(str(project) if project else None)


class TestBaseUrl:
    def test_defaults_to_deepseek(self, tmp_path, monkeypatch):
        assert _load(tmp_path, monkeypatch, "").base_url == DEFAULT_BASE_URL

    def test_read_from_toml(self, tmp_path, monkeypatch):
        c = _load(tmp_path, monkeypatch, 'base_url = "https://openrouter.ai/api/v1"\n')
        assert c.base_url == "https://openrouter.ai/api/v1"

    def test_trailing_slash_is_trimmed(self, tmp_path, monkeypatch):
        c = _load(tmp_path, monkeypatch, 'base_url = "https://example.test/v1/"\n')
        assert c.base_url == "https://example.test/v1"

    def test_env_var_wins(self, tmp_path, monkeypatch):
        global_file = tmp_path / "config.toml"
        global_file.write_text('base_url = "https://from-file.test"\n')
        monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", global_file)
        monkeypatch.setattr(cfg, "_OLD_CONFIG_FILE", tmp_path / "absent")
        monkeypatch.setenv("SUPERVIS_BASE_URL", "https://from-env.test")

        assert cfg.load_config().base_url == "https://from-env.test"

    def test_project_config_can_override_the_endpoint(self, tmp_path, monkeypatch):
        c = _load(
            tmp_path,
            monkeypatch,
            'base_url = "https://global.test"\n',
            project_toml='base_url = "https://project.test"\n',
        )
        assert c.base_url == "https://project.test"

    def test_provider_neutral_api_key_var(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(cfg, "_OLD_CONFIG_FILE", tmp_path / "absent-old")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("SUPERVIS_API_KEY", "sk-neutral")
        assert cfg.load_config().api_key == "sk-neutral"

    def test_legacy_deepseek_key_var_still_works(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "_GLOBAL_CONFIG_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(cfg, "_OLD_CONFIG_FILE", tmp_path / "absent-old")
        monkeypatch.delenv("SUPERVIS_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-legacy")
        assert cfg.load_config().api_key == "sk-legacy"


class TestProModelResolution:
    def test_untouched_config_keeps_deepseek_tiering(self, tmp_path, monkeypatch):
        c = _load(tmp_path, monkeypatch, "")
        assert c.model == DEFAULT_MODEL
        assert c.pro_model == DEFAULT_PRO_MODEL

    def test_a_custom_model_collapses_tiering_instead_of_escalating_to_deepseek(self, tmp_path, monkeypatch):
        """Escalating to deepseek-v4-pro on someone else's endpoint would just 404."""
        c = _load(tmp_path, monkeypatch, 'base_url = "https://openrouter.ai/api/v1"\nmodel = "moonshotai/kimi-k2"\n')
        assert c.pro_model == "moonshotai/kimi-k2"

    def test_an_explicit_pro_model_is_respected(self, tmp_path, monkeypatch):
        c = _load(
            tmp_path,
            monkeypatch,
            'model = "provider/small"\npro_model = "provider/large"\n',
        )
        assert c.pro_model == "provider/large"


class TestPricingSection:
    def test_rates_from_config_are_registered(self, tmp_path, monkeypatch):
        _load(
            tmp_path,
            monkeypatch,
            'model = "acme/big"\n\n[pricing."acme/big"]\ninput = 0.6\ncached = 0.15\noutput = 2.5\n',
        )
        assert price_for("acme/big") == (0.6, 0.15, 2.5)

    def test_cached_is_optional(self, tmp_path, monkeypatch):
        _load(tmp_path, monkeypatch, '[pricing."acme/plain"]\ninput = 1.0\noutput = 3.0\n')
        assert price_for("acme/plain") == (1.0, 1.0, 3.0)

    def test_an_incomplete_entry_is_warned_about_and_skipped(self, tmp_path, monkeypatch, capsys):
        _load(tmp_path, monkeypatch, '[pricing."acme/partial"]\ninput = 1.0\n')
        assert price_for("acme/partial") is None
        assert "acme/partial" in capsys.readouterr().err

    def test_non_numeric_rates_are_warned_about_and_skipped(self, tmp_path, monkeypatch, capsys):
        _load(tmp_path, monkeypatch, '[pricing."acme/bad"]\ninput = "free"\noutput = "also free"\n')
        assert price_for("acme/bad") is None
        assert "acme/bad" in capsys.readouterr().err


class TestRequestShape:
    async def _capture_extra_body(self, model: str) -> dict | None:
        session = Session(client=MagicMock())
        session.messages = [{"role": "system", "content": "sys"}]
        session.model = model

        empty_stream = MagicMock()
        empty_stream.__aiter__ = lambda self: _empty()
        session.client.chat.completions.create = AsyncMock(return_value=empty_stream)

        await _api_call(session)
        return session.client.chat.completions.create.await_args.kwargs["extra_body"]

    @pytest.mark.asyncio
    async def test_deepseek_models_get_the_thinking_toggle(self):
        extra = await self._capture_extra_body("deepseek-v4-flash")
        assert extra == {"thinking": {"type": "enabled"}}

    @pytest.mark.asyncio
    async def test_third_party_models_get_no_deepseek_extensions(self):
        """`thinking` is a DeepSeek extension; sending it elsewhere is a 400 waiting to happen."""
        assert await self._capture_extra_body("moonshotai/kimi-k2") is None
        assert await self._capture_extra_body("gpt-4o-mini") is None


async def _empty():
    return
    yield  # pragma: no cover


class TestModelCommandOffDeepSeek:
    def _app(self, base_url: str):
        from tests.test_commands import FakeApp

        app = FakeApp()
        app.session.base_url = base_url
        return app

    def test_an_arbitrary_id_is_accepted_on_a_third_party_endpoint(self):
        app = self._app("https://openrouter.ai/api/v1")
        dispatch("/model moonshotai/kimi-k2", app)
        assert app.session.model == "moonshotai/kimi-k2"
        assert app.session.pinned is True

    def test_a_typo_is_still_caught_on_deepseek(self):
        app = self._app(DEFAULT_BASE_URL)
        dispatch("/model prro", app)
        assert app.session.pinned is False
        assert "Unknown model" in app.log.text

    def test_named_profiles_still_work_off_deepseek(self):
        app = self._app("https://openrouter.ai/api/v1")
        dispatch("/model pro", app)
        assert app.session.model == "deepseek-v4-pro"


class TestClientWiring:
    def test_the_client_is_built_against_the_configured_endpoint(self):
        config = Config(api_key="sk-test", base_url="https://openrouter.ai/api/v1")
        app = SupervisApp(project_dir="/tmp/p", system_prompt="sys", config=config)
        assert str(app.session.client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
        assert app.session.base_url == "https://openrouter.ai/api/v1"

    def test_config_command_shows_the_endpoint(self):
        from tests.test_commands import FakeApp

        app = FakeApp()
        app.session.base_url = "https://openrouter.ai/api/v1"
        with patch("supervisor.commands.DEFAULT_BASE_URL", DEFAULT_BASE_URL):
            dispatch("/config", app)
        assert "https://openrouter.ai/api/v1" in app.log.text
