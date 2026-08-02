"""Per-model token pricing.

One place to keep token prices. CostTracker computes the running dollar total
from these rates at record() time, so a session that mixes models (flash for
routine drive steps, pro when escalated) is billed correctly per tier.

DeepSeek rates are USD per 1M tokens, from api-docs.deepseek.com (verified
2026-08-02). Update the numbers here when DeepSeek changes the rate card.

Watch item: DeepSeek has announced 2x pricing during two daily Beijing-time peak
windows. No effective date has been published, so the rates below are the flat
ones. When that lands, this table needs a time-of-day dimension.

Because supervis can point at any OpenAI-compatible endpoint, a model may have
no entry here at all. price_for() returns None in that case rather than guessing
— quoting DeepSeek's rates for somebody else's model would be worse than saying
nothing. Users can supply rates for their own models with a [pricing] section in
config.toml; see register_pricing().
"""

# model id -> (input_miss, input_cached, output) per 1M tokens
Rates = tuple[float, float, float]

PRICING: dict[str, Rates] = {
    "deepseek-v4-flash": (0.14, 0.0028, 0.28),
    "deepseek-v4-pro": (0.435, 0.003625, 0.87),
    # Legacy ids were retired 2026-07-24; configs naming them are remapped to v4-flash, so price them as flash.
    "deepseek-chat": (0.14, 0.0028, 0.28),
    "deepseek-reasoner": (0.14, 0.0028, 0.28),
}

# Rates supplied by the user's config, for models this table has never heard of.
_USER_PRICING: dict[str, Rates] = {}


def register_pricing(model: str, input_miss: float, output: float, cached: float | None = None) -> None:
    """Teach the tracker what a model costs. Called from config loading.

    `cached` defaults to the cache-miss rate, which is the pessimistic reading:
    a provider without prompt caching bills every input token at full price.
    """
    _USER_PRICING[model] = (input_miss, cached if cached is not None else input_miss, output)


def clear_user_pricing() -> None:
    """Drop config-supplied rates. Exists so tests don't leak into each other."""
    _USER_PRICING.clear()


def price_for(model: str) -> Rates | None:
    """Return (input_miss, input_cached, output) per 1M tokens, or None if unknown."""
    return _USER_PRICING.get(model) or PRICING.get(model)
