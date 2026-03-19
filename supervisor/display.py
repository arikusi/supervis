"""Terminal display helpers — colors, banners, tags."""

R       = "\033[0m"
CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
BOLD    = "\033[1m"
DIM     = "\033[2m"


def banner(text: str, color: str = CYAN) -> None:
    print(f"\n{color}{BOLD}{'─' * 60}{R}")
    print(f"{color}{BOLD}  {text}{R}")
    print(f"{color}{BOLD}{'─' * 60}{R}", flush=True)


def header() -> None:
    print(f"\n{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗{R}")
    print(f"{CYAN}{BOLD}║          DeepSeek Supervisor × Claude Code           ║{R}")
    print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════╝{R}")


def tool_tag(label: str) -> None:
    print(f"{MAGENTA}{DIM}[{label}]{R} ", flush=True)
