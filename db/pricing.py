"""Static per-model pricing, used to compute `cost_usd` once at insert time.

Input/output rates below are user-confirmed. Anthropic doesn't publish separate
cache rates for every model, so cache_write/cache_read are derived from each
model's input rate using Anthropic's standard 5m-ephemeral-cache multipliers
(1.25x input for a cache write, 0.1x input for a cache read) rather than being
independently confirmed per model.
"""


def _with_standard_cache_rates(input_rate: float, output_rate: float) -> tuple:
    return (input_rate, output_rate, input_rate * 1.25, input_rate * 0.1)


# model_name: (input $/M tok, output $/M tok, cache_write $/M tok, cache_read $/M tok)
PRICING = {
    "claude-haiku-4-5": _with_standard_cache_rates(1.00, 5.00),
    "claude-sonnet-5": _with_standard_cache_rates(2.00, 10.00),
    "claude-opus-5": _with_standard_cache_rates(5.00, 25.00),
    "claude-fable-5": _with_standard_cache_rates(10.00, 50.00),
}


def compute_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float | None:
    """Return cost in USD, or None if `model` has no entry in PRICING.

    None (not 0) is deliberate: an unrecognized model's cost is unknown, not free.
    """
    rates = PRICING.get(model)
    if rates is None:
        return None
    input_rate, output_rate, cache_write_rate, cache_read_rate = rates
    return (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_write_tokens * cache_write_rate
        + cache_read_tokens * cache_read_rate
    ) / 1_000_000
