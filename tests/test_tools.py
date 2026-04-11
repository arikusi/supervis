"""Tests for supervisor.tools module (non-Claude tools only)."""

from supervisor.tools import _get_git_status, _list_files, _read_file, _run_shell


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
