"""Static per-model pricing, used to compute `cost_usd` once at insert time.

All five rates per model (input, output, 1h cache write, 5m cache write, cache
read) are confirmed directly against Anthropic's own published pricing page
(checked 2026-08-12) rather than derived or assumed. Anthropic bills a cache
write at one of two tiers depending on the requested TTL -- 2x input for a
1-hour cache, 1.25x input for a 5-minute cache -- which cost meaningfully
different amounts; real ingested usage shows the 1-hour tier is the dominant
one (86% of cache-write tokens across every session on this machine), so
collapsing both into a single derived rate had been undercounting cache-write
cost by roughly 50%.

`inference_geo` (a 1.1x multiplier for US-only routing) and fast-mode pricing
are known additional multipliers Anthropic applies in some cases. Neither is
modeled here, since no ingested usage currently uses them -- add support if
that changes.
"""

# model_name: (input, output, cache_write_1h, cache_write_5m, cache_read), all $/M tok
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00, 2.00, 1.25, 0.10),
    "claude-sonnet-5": (2.00, 10.00, 4.00, 2.50, 0.20),
    "claude-opus-5": (5.00, 25.00, 10.00, 6.25, 0.50),
    "claude-fable-5": (10.00, 50.00, 20.00, 12.50, 1.00),
    "claude-sonnet-4-6": (3.00, 15.00, 6.00, 3.75, 0.30),
}


def compute_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_1h_tokens: int,
    cache_write_5m_tokens: int,
) -> float | None:
    """Return cost in USD, or None if `model` has no entry in PRICING.

    None (not 0) is deliberate: an unrecognized model's cost is unknown, not free.
    """
    rates = PRICING.get(model) if model is not None else None
    if rates is None:
        return None
    (
        input_rate,
        output_rate,
        cache_write_1h_rate,
        cache_write_5m_rate,
        cache_read_rate,
    ) = rates
    return (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_write_1h_tokens * cache_write_1h_rate
        + cache_write_5m_tokens * cache_write_5m_rate
        + cache_read_tokens * cache_read_rate
    ) / 1_000_000
