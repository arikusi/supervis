"""Tool definitions and implementations for DeepSeek."""

import glob as _glob
import subprocess
from pathlib import Path
from .claude import run_claude
from .display import MAGENTA, DIM, R

# ─── Definitions ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's contents from the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files matching a glob pattern. Example: 'src/**/*.py'",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"}
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a text pattern in the codebase (grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a read-only shell command (ls, git log, cat, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_status",
            "description": "Get git status and diff to see what Claude Code changed.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_claude",
            "description": (
                "Send a task to Claude Code. It will write/edit/run files autonomously. "
                "Be specific: include file names, function signatures, and acceptance criteria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "continue_session": {
                        "type": "boolean",
                        "description": "True to continue previous Claude session (keeps context).",
                        "default": True,
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]

# ─── Implementations ─────────────────────────────────────────────────────────

_SKIP = {".git/", "__pycache__", "node_modules", ".venv"}


def _read_file(path: str) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8")
        lines = content.splitlines()
        if len(lines) > 300:
            return "\n".join(lines[:300]) + f"\n... ({len(lines)} lines total)"
        return content
    except Exception as e:
        return f"Error: {e}"


def _list_files(pattern: str) -> str:
    files = _glob.glob(pattern, recursive=True)
    files = [f for f in files if not any(s in f for s in _SKIP)]
    return "\n".join(sorted(files)[:100]) if files else "No files found."


def _search_code(pattern: str, path: str = ".") -> str:
    try:
        result = subprocess.run(
            ["grep", "-r", "-n", pattern, path],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.splitlines() if not any(s in l for s in _SKIP)]
        return "\n".join(lines[:80]) if lines else "No matches."
    except Exception as e:
        return f"Error: {e}"


def _run_shell(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15
        )
        out = (result.stdout + result.stderr).strip()
        return out[:3000] if out else "(no output)"
    except Exception as e:
        return f"Error: {e}"


def _get_git_status() -> str:
    status = _run_shell("git status --short")
    diff   = _run_shell("git diff --stat HEAD 2>/dev/null || git diff --stat")
    log    = _run_shell("git log --oneline -5 2>/dev/null || echo 'no git log'")
    return f"=== Status ===\n{status}\n\n=== Diff ===\n{diff}\n\n=== Recent commits ===\n{log}"


# ─── Dispatcher ──────────────────────────────────────────────────────────────

async def execute_tool(name: str, args: dict) -> str:
    labels = {
        "read_file":     f"📄 {args.get('path', '')}",
        "list_files":    f"📁 {args.get('pattern', '')}",
        "search_code":   f"🔍 '{args.get('pattern', '')}'",
        "run_shell":     f"$ {args.get('command', '')[:50]}",
        "get_git_status": "git status",
        "run_claude":    "→ Claude Code",
    }
    if name != "run_claude":
        print(f"{MAGENTA}{DIM}[{labels.get(name, name)}]{R}", flush=True)

    match name:
        case "read_file":
            return _read_file(args["path"])
        case "list_files":
            return _list_files(args["pattern"])
        case "search_code":
            return _search_code(args["pattern"], args.get("path", "."))
        case "run_shell":
            return _run_shell(args["command"])
        case "get_git_status":
            return _get_git_status()
        case "run_claude":
            return await run_claude(args["prompt"], args.get("continue_session", True))
        case _:
            return f"Unknown tool: {name}"
