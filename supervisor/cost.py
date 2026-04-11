"""Session token and cost tracking."""

# DeepSeek V3.2 pricing (per 1M tokens) — updated March 2026
_PRICE_INPUT = 0.28  # cache miss
_PRICE_INPUT_CACHED = 0.028  # cache hit (90% off)
_PRICE_OUTPUT = 0.42

_session_input = 0
_session_input_cached = 0
_session_output = 0


def record(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> None:
    global _session_input, _session_input_cached, _session_output
    _session_input += input_tokens - cached_tokens
    _session_input_cached += cached_tokens
    _session_output += output_tokens


def session_cost() -> float:
    return (
        _session_input / 1_000_000 * _PRICE_INPUT
        + _session_input_cached / 1_000_000 * _PRICE_INPUT_CACHED
        + _session_output / 1_000_000 * _PRICE_OUTPUT
    )


def summary() -> str:
    total_in = _session_input + _session_input_cached
    cached = _session_input_cached
    out = _session_output
    cost = session_cost()

    cached_note = f"  {cached / 1000:.1f}k cached" if cached else ""
    return f"in {total_in / 1000:.1f}k{cached_note} · out {out / 1000:.1f}k · ${cost:.4f}"


def reset() -> None:
    global _session_input, _session_input_cached, _session_output
    _session_input = _session_input_cached = _session_output = 0
