"""orca_code.cost_estimator — Tool call cost estimation (P2-69).

Estimates API token cost before execution based on expected token usage
and model pricing. Helps users understand cost implications.

Pricing per 1M tokens (approximate, USD):
  deepseek-chat:      $0.14 input / $0.28 output
  deepseek-reasoner:  $0.55 input / $2.19 output
  gpt-4o:             $2.50 input / $10.00 output
  gpt-4o-mini:        $0.15 input / $0.60 output
  claude-sonnet-4:    $3.00 input / $15.00 output
"""

from __future__ import annotations

MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-20250514": {"input": 0.80, "output": 4.00},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> dict:
    """Estimate cost for a given number of tokens.

    Returns dict with input_cost, output_cost, total_cost in USD.
    """
    pricing = MODEL_PRICING.get(model, {"input": 0.50, "output": 1.00})
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return {
        "input_cost": round(input_cost, 4),
        "output_cost": round(output_cost, 4),
        "total_cost": round(input_cost + output_cost, 4),
        "pricing_per_1m_input": pricing["input"],
        "pricing_per_1m_output": pricing["output"],
    }


def format_cost(model: str, input_tokens: int, output_tokens: int = 0) -> str:
    """Format cost estimate as human-readable string."""
    c = estimate_cost(model, input_tokens, output_tokens)
    total = c["total_cost"]
    if total < 0.001:
        return f"~${total:.6f} (negligible)"
    elif total < 0.01:
        return f"~${total:.4f}"
    else:
        return f"~${total:.3f} (↑{input_tokens} ↓{output_tokens} tokens)"
