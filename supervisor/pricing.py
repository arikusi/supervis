"""Per-model DeepSeek pricing.

One place to keep token prices. CostTracker computes the running dollar total
from these rates at record() time, so a session that mixes models (flash for
routine drive steps, pro when escalated) is billed correctly per tier.

Rates are USD per 1M tokens, from api-docs.deepseek.com (verified 2026-08-02).
Update the numbers here when DeepSeek changes the rate card.

Watch item: DeepSeek has announced 2x pricing during two daily Beijing-time peak
windows. No effective date has been published, so the rates below are the flat
ones. When that lands, this table needs a time-of-day dimension.
"""

# model id -> (input_miss, input_cached, output) per 1M tokens
PRICING: dict[str, tuple[float, float, float]] = {
    "deepseek-v4-flash": (0.14, 0.0028, 0.28),
    "deepseek-v4-pro": (0.435, 0.003625, 0.87),
    # Legacy ids were retired 2026-07-24; configs naming them are remapped to v4-flash, so price them as flash.
    "deepseek-chat": (0.14, 0.0028, 0.28),
    "deepseek-reasoner": (0.14, 0.0028, 0.28),
}

# Used when an unknown model id shows up — flash rates are the safe (cheapest) default.
_DEFAULT = PRICING["deepseek-v4-flash"]


def price_for(model: str) -> tuple[float, float, float]:
    """Return (input_miss, input_cached, output) per 1M tokens for a model id."""
    return PRICING.get(model, _DEFAULT)
