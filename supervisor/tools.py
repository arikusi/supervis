"""Tool definitions and implementations for DeepSeek."""

import glob as _glob
import subprocess
from pathlib import Path
from .claude import run_claude
from .display import DIM, R

# ─── Definitions ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_claude",
            "description": (
                "Send a task to Claude Code. Claude Code reads, writes, edits, tests, "
                "and runs code autonomously. Be specific: include file names, function "
                "signatures, requirements, and acceptance criteria. Ask Claude Code to "
                "verify its own work or run tests as part of the prompt."
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
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file to understand context before giving instructions to Claude Code.",
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
            "description": "List files matching a glob pattern to understand project structure.",
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
            "description": "Search for a text pattern in the codebase.",
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
            "name": "get_git_status",
            "description": "Quick check on what changed in the repo.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a quick shell command (git log, ls, npm run build, etc.). For fast checks only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"],
            },
        },
    },
]

# ─── Implementations ─────────────────────────────────────────────────────────

_SKIP = {".git/", "__pycache__", "node_modules", ".venv", ".next"}


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
            ["grep", "-r", "-n", "--include=*.py", "--include=*.ts", "--include=*.tsx",
             "--include=*.js", "--include=*.jsx", "--include=*.json", "--include=*.md",
             pattern, path],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.splitlines() if not any(s in l for s in _SKIP)]
        return "\n".join(lines[:80]) if lines else "No matches."
    except Exception as e:
        return f"Error: {e}"


def _run_shell(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15,
        )
        out = (result.stdout + result.stderr).strip()
        return out[:3000] if out else "(no output)"
    except Exception as e:
        return f"Error: {e}"


def _get_git_status() -> str:
    try:
        result = subprocess.run(
            "git status --short && echo '---' && git log --oneline -5 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "(clean)"
    except Exception as e:
        return f"Error: {e}"


# ─── Dispatcher ──────────────────────────────────────────────────────────────

_TOOL_LABELS = {
    "read_file":      lambda a: f"read {a.get('path', '')}",
    "list_files":     lambda a: f"ls {a.get('pattern', '')}",
    "search_code":    lambda a: f"grep '{a.get('pattern', '')}'",
    "get_git_status": lambda a: "git status",
    "run_shell":      lambda a: f"$ {a.get('command', '')[:50]}",
}


async def execute_tool(name: str, args: dict) -> str:
    if name == "run_claude":
        return await run_claude(args["prompt"], args.get("continue_session", True))

    label_fn = _TOOL_LABELS.get(name)
    if label_fn:
        print(f"  {DIM}[{label_fn(args)}]{R}", flush=True)

    match name:
        case "read_file":
            return _read_file(args["path"])
        case "list_files":
            return _list_files(args["pattern"])
        case "search_code":
            return _search_code(args["pattern"], args.get("path", "."))
        case "get_git_status":
            return _get_git_status()
        case "run_shell":
            return _run_shell(args["command"])
        case _:
            return f"Unknown tool: {name}"
