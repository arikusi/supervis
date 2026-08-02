"""Tests for the slash command registry and the built-in commands.

Commands take (app, args) and talk to the app through query_one() and a handful
of attributes, so a small stand-in stands in for the whole TUI.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from supervisor.commands import dispatch, get_help, register
from supervisor.queue import MessageQueue
from supervisor.session import Session


class FakeLog:
    """Records what a command printed."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_system(self, text: str) -> None:
        self.lines.append(text)

    def write_help(self, entries) -> None:
        self.lines.extend(f"/{name} — {desc}" for name, desc in entries)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class FakeStatus:
    def __init__(self) -> None:
        self.model_text = ""
        self.cost_text = ""


class FakeApp:
    def __init__(self, session: Session | None = None) -> None:
        self.log = FakeLog()
        self.status = FakeStatus()
        client = MagicMock()
        client.api_key = "sk-abcdefghijklmnop"
        self.session = session or Session(client=client)
        self._project_dir = "/tmp/project"
        self._user_queue = MessageQueue()
        self.reset_called = False
        self.help_called = False

    def query_one(self, selector, _type=None):
        return self.log if selector == "#output" else self.status

    def handle_reset(self) -> None:
        self.reset_called = True

    def handle_help(self) -> None:
        self.help_called = True


class TestDispatch:
    def test_plain_text_is_not_a_command(self):
        assert dispatch("build me a website", FakeApp()) is False

    def test_unknown_command_is_not_handled(self):
        app = FakeApp()
        assert dispatch("/definitely-not-a-command", app) is False

    def test_known_command_is_handled(self):
        app = FakeApp()
        assert dispatch("/status", app) is True

    def test_command_name_is_case_insensitive(self):
        app = FakeApp()
        assert dispatch("/STATUS", app) is True

    def test_arguments_are_passed_through(self):
        seen = {}

        @register("_testcmd")
        def _handler(app, args):
            seen["args"] = args

        dispatch("/_testcmd  flash  extra ", FakeApp())
        # everything after the command name is handed over untouched; handlers
        # do their own strip()
        assert seen["args"] == "flash  extra "

    def test_bare_slash_is_not_handled(self):
        assert dispatch("/", FakeApp()) is False

    def test_help_registry_has_descriptions(self):
        entries = dict(get_help())
        for name in ("reset", "model", "status", "budget", "export", "queue", "cancel"):
            assert entries.get(name), f"/{name} is missing a help description"


class TestModelCommand:
    def test_bare_model_reports_the_active_tier(self):
        app = FakeApp()
        dispatch("/model", app)
        assert "deepseek-v4-flash" in app.log.text
        assert "auto-tiering" in app.log.text

    def test_pinning_sets_the_model_and_disables_tiering(self):
        app = FakeApp()
        dispatch("/model pro", app)
        assert app.session.pinned is True
        assert app.session.model == "deepseek-v4-pro"
        assert app.status.model_text == "deepseek-v4-pro"

    def test_fast_profile_turns_thinking_off(self):
        app = FakeApp()
        dispatch("/model flash-fast", app)
        assert app.session.model == "deepseek-v4-flash"
        assert app.session.thinking is False

    def test_auto_returns_to_tiering(self):
        app = FakeApp()
        dispatch("/model pro", app)
        dispatch("/model auto", app)
        assert app.session.pinned is False
        assert app.status.model_text == app.session.base_model

    def test_unknown_profile_is_rejected_without_changing_state(self):
        app = FakeApp()
        dispatch("/model banana", app)
        assert app.session.pinned is False
        assert "Unknown model" in app.log.text

    def test_legacy_alias_maps_to_a_v4_profile(self):
        app = FakeApp()
        dispatch("/model reasoner", app)
        assert app.session.model == "deepseek-v4-pro"


class TestAutoCommand:
    @pytest.mark.parametrize("arg", ["on", "true", "yes"])
    def test_enables(self, arg):
        app = FakeApp()
        app.session.auto_escalate = False
        dispatch(f"/auto {arg}", app)
        assert app.session.auto_escalate is True

    @pytest.mark.parametrize("arg", ["off", "false", "no"])
    def test_disables(self, arg):
        app = FakeApp()
        dispatch(f"/auto {arg}", app)
        assert app.session.auto_escalate is False

    def test_bare_auto_reports_state_without_changing_it(self):
        app = FakeApp()
        dispatch("/auto", app)
        assert app.session.auto_escalate is True
        assert "Auto-escalation is on" in app.log.text


class TestStatusAndConfig:
    def test_status_reports_the_essentials(self):
        app = FakeApp()
        dispatch("/status", app)
        text = app.log.text
        assert "Model:" in text
        assert "Cost:" in text
        assert "/tmp/project" in text

    def test_status_shows_escalation(self):
        app = FakeApp()
        app.session.model = app.session.pro_model
        dispatch("/status", app)
        assert "escalated" in app.log.text

    def test_config_masks_the_api_key(self):
        app = FakeApp()
        dispatch("/config", app)
        text = app.log.text
        assert "sk-abcdefghijklmnop" not in text, "the key must never be printed in full"
        assert "sk-" in text and "..." in text

    def test_config_lists_the_limits(self):
        app = FakeApp()
        dispatch("/config", app)
        assert "max_turns" in app.log.text
        assert "claude_timeout" in app.log.text


class TestBudget:
    def test_without_a_limit_it_just_reports_spend(self):
        app = FakeApp()
        dispatch("/budget", app)
        assert "No budget limit set" in app.log.text

    def test_with_a_limit_it_reports_the_remainder(self):
        app = FakeApp()
        app.session.max_cost = 1.0
        app.session.cost.record(1_000_000, 0, model="deepseek-v4-flash")  # $0.14
        dispatch("/budget", app)
        text = app.log.text
        assert "$0.1400 / $1.00" in text
        assert "Remaining: $0.8600" in text


class TestQueueCommands:
    def test_queue_lists_pending_messages(self):
        app = FakeApp()
        app._user_queue.put("first")
        app._user_queue.put("second")
        dispatch("/queue", app)
        assert "first" in app.log.text
        assert "second" in app.log.text

    def test_queue_says_so_when_empty(self):
        app = FakeApp()
        dispatch("/queue", app)
        assert "No queued messages" in app.log.text

    def test_cancel_by_index_removes_only_that_one(self):
        app = FakeApp()
        app._user_queue.put("keep me")
        app._user_queue.put("drop me")
        dispatch("/cancel 1", app)
        assert app._user_queue.pending() == ["keep me"]

    def test_cancel_without_index_clears_everything(self):
        app = FakeApp()
        app._user_queue.put("a")
        app._user_queue.put("b")
        dispatch("/cancel", app)
        assert app._user_queue.pending() == []

    def test_cancel_with_a_bad_index_is_reported(self):
        app = FakeApp()
        app._user_queue.put("a")
        dispatch("/cancel 9", app)
        assert "Invalid index" in app.log.text
        assert app._user_queue.pending() == ["a"]


class TestReasoningAndReset:
    def test_reasoning_toggles(self):
        app = FakeApp()
        dispatch("/reasoning", app)
        assert app.session.show_reasoning is True
        dispatch("/reasoning", app)
        assert app.session.show_reasoning is False

    def test_reset_delegates_to_the_app(self):
        app = FakeApp()
        dispatch("/reset", app)
        assert app.reset_called is True

    def test_help_delegates_to_the_app(self):
        app = FakeApp()
        dispatch("/help", app)
        assert app.help_called is True


class TestExport:
    def test_markdown_export_skips_the_system_prompt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = FakeApp()
        app.session.messages = [
            {"role": "system", "content": "SECRET SYSTEM PROMPT"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        dispatch("/export md", app)

        written = list(tmp_path.glob("supervis-export-*.md"))
        assert len(written) == 1
        body = written[0].read_text()
        assert "SECRET SYSTEM PROMPT" not in body
        assert "hello" in body and "hi there" in body

    def test_json_export_round_trips(self, tmp_path, monkeypatch):
        import json

        monkeypatch.chdir(tmp_path)
        app = FakeApp()
        app.session.messages = [{"role": "user", "content": "ünïcode"}]
        dispatch("/export json", app)

        written = list(tmp_path.glob("supervis-export-*.json"))
        assert json.loads(written[0].read_text()) == app.session.messages

    def test_unknown_format_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = FakeApp()
        dispatch("/export pdf", app)
        assert "Usage" in app.log.text
        assert list(tmp_path.glob("supervis-export-*")) == []


class TestUpdate:
    def test_reports_an_available_update(self):
        app = FakeApp()
        with patch("supervisor.version_check.check_for_update_sync", return_value=("1.0.0", "9.9.9")):
            dispatch("/update", app)
        assert "9.9.9" in app.log.text

    def test_reports_being_current(self):
        app = FakeApp()
        with patch("supervisor.version_check.check_for_update_sync", return_value=("1.0.0", None)):
            dispatch("/update", app)
        assert "up to date" in app.log.text


class TestUndo:
    def test_stashes_when_there_are_changes(self):
        app = FakeApp()
        results = [
            SimpleNamespace(stdout=" file.py | 2 +-\n", stderr=""),
            SimpleNamespace(stdout="Saved working directory\n", stderr=""),
        ]
        with patch("subprocess.run", side_effect=results) as run:
            dispatch("/undo", app)
        assert "git stash" in run.call_args_list[1][0][0]
        assert "Saved working directory" in app.log.text

    def test_reverts_when_the_tree_is_clean(self):
        app = FakeApp()
        results = [
            SimpleNamespace(stdout="", stderr=""),
            SimpleNamespace(stdout="Revert done\n", stderr=""),
        ]
        with patch("subprocess.run", side_effect=results) as run:
            dispatch("/undo", app)
        assert "git revert" in run.call_args_list[1][0][0]
