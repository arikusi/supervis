"""Tests for supervisor.tools module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supervisor.session import Session
from supervisor.tools import (
    TOOLS,
    _get_git_status,
    _list_files,
    _read_file,
    _run_shell,
    _search_code,
    execute_tool,
)


class TestReadFile:
    def test_reads_normal_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3")
        result = _read_file(str(f))
        assert result == "line1\nline2\nline3"

    def test_truncates_long_file(self, tmp_path):
        f = tmp_path / "big.txt"
        lines = [f"line {i}" for i in range(500)]
        f.write_text("\n".join(lines))
        result = _read_file(str(f))
        assert "... (500 lines total)" in result
        assert result.count("\n") == 300  # 300 lines + truncation message

    def test_missing_file(self):
        result = _read_file("/nonexistent/path/foo.txt")
        assert result.startswith("Error:")


class TestListFiles:
    def test_finds_files(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        result = _list_files(str(tmp_path / "*.py"))
        assert "a.py" in result
        assert "b.py" in result

    def test_skips_excluded_dirs(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x.py").touch()
        (tmp_path / "good.py").touch()
        result = _list_files(str(tmp_path / "**" / "*.py"))
        assert "node_modules" not in result
        assert "good.py" in result

    def test_no_matches(self, tmp_path):
        result = _list_files(str(tmp_path / "*.xyz"))
        assert result == "No files found."


class TestRunShell:
    def test_basic_command(self):
        result = _run_shell("echo hello")
        assert result.strip() == "hello"

    def test_captures_stderr(self):
        result = _run_shell("echo err >&2")
        assert "err" in result

    def test_empty_output(self):
        result = _run_shell("true")
        assert result == "(no output)"

    def test_truncates_long_output(self):
        result = _run_shell("python -c \"print('x' * 5000)\"")
        assert len(result) <= 3000


class TestRunShellBlocklist:
    def test_blocks_rm_rf_root(self):
        result = _run_shell("rm -rf /")
        assert "blocked" in result.lower()

    def test_blocks_rm_rf_home(self):
        result = _run_shell("rm -rf ~")
        assert "blocked" in result.lower()

    def test_blocks_mkfs(self):
        result = _run_shell("mkfs.ext4 /dev/sda1")
        assert "blocked" in result.lower()

    def test_blocks_fork_bomb(self):
        result = _run_shell(":(){ :|:& };:")
        assert "blocked" in result.lower()

    def test_blocks_case_insensitive(self):
        result = _run_shell("RM -RF /")
        assert "blocked" in result.lower()

    def test_allows_safe_commands(self):
        result = _run_shell("echo safe")
        assert result.strip() == "safe"

    def test_allows_rm_in_project(self):
        result = _run_shell("rm -rf ./build")
        assert "blocked" not in result.lower()


class TestGetGitStatus:
    def test_returns_string(self):
        result = _get_git_status()
        assert isinstance(result, str)
        assert len(result) > 0


class TestSearchCode:
    def test_finds_a_match(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.py").write_text("def handler():\n    return 42\n")
        result = _search_code("handler", ".")
        assert "app.py" in result
        assert "def handler" in result

    def test_reports_no_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.py").write_text("nothing here\n")
        assert _search_code("zzz-not-present", ".") == "No matches."

    def test_skips_noise_directories(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "real.py").write_text("needle\n")
        vendored = tmp_path / "node_modules"
        vendored.mkdir()
        (vendored / "dep.py").write_text("needle\n")

        result = _search_code("needle", ".")
        assert "real.py" in result
        assert "node_modules" not in result


class TestExecuteToolDispatch:
    @pytest.mark.asyncio
    async def test_unknown_tool_is_reported_not_raised(self):
        session = Session(client=MagicMock())
        result = await execute_tool("not_a_real_tool", {}, session)
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_escalate_flags_the_next_turn_for_pro(self):
        session = Session(client=MagicMock())
        result = await execute_tool("escalate", {"reason": "architectural call"}, session)

        assert "deepseek-v4-pro" in result
        changed, _ = session.select_turn_model()
        assert changed and session.model == session.pro_model

    @pytest.mark.asyncio
    async def test_run_shell_uses_the_session_timeout(self):
        session = Session(client=MagicMock())
        session.shell_timeout = 7
        with patch("supervisor.tools._run_shell", return_value="ok") as shell:
            await execute_tool("run_shell", {"command": "echo hi"}, session)
        assert shell.call_args.kwargs["timeout"] == 7

    @pytest.mark.asyncio
    async def test_run_claude_is_forwarded_with_the_session(self):
        session = Session(client=MagicMock())
        with patch("supervisor.tools.run_claude", new_callable=AsyncMock, return_value="done") as rc:
            result = await execute_tool("run_claude", {"prompt": "build it"}, session)

        assert result == "done"
        assert rc.await_args.args[0] == "build it"
        assert rc.await_args.kwargs["session"] is session

    @pytest.mark.asyncio
    async def test_continue_session_defaults_to_true(self):
        session = Session(client=MagicMock())
        with patch("supervisor.tools.run_claude", new_callable=AsyncMock, return_value="") as rc:
            await execute_tool("run_claude", {"prompt": "x"}, session)
        assert rc.await_args.args[1] is True

    @pytest.mark.asyncio
    async def test_read_and_list_reach_their_implementations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "note.txt").write_text("contents here\n")
        session = Session(client=MagicMock())

        assert "contents here" in await execute_tool("read_file", {"path": "note.txt"}, session)
        assert "note.txt" in await execute_tool("list_files", {"pattern": "*.txt"}, session)

    @pytest.mark.asyncio
    async def test_git_status_runs(self):
        session = Session(client=MagicMock())
        result = await execute_tool("get_git_status", {}, session)
        assert isinstance(result, str)


class TestToolSchema:
    def test_every_tool_has_a_name_and_description(self):
        for tool in TOOLS:
            fn = tool["function"]
            assert fn["name"], tool
            assert fn["description"], fn["name"]

    def test_run_claude_requires_a_prompt(self):
        run_claude_def = next(t["function"] for t in TOOLS if t["function"]["name"] == "run_claude")
        assert run_claude_def["parameters"]["required"] == ["prompt"]

    def test_dispatcher_handles_every_advertised_tool(self):
        """A tool the model can call but the dispatcher does not know is a dead end."""
        import inspect

        from supervisor import tools

        source = inspect.getsource(tools.execute_tool)
        for tool in TOOLS:
            name = tool["function"]["name"]
            assert f'"{name}"' in source, f"{name} is advertised but not dispatched"
