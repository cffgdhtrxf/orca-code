"""orca_code.sparkline — ASCII sparkline charts (P2-90).

Generates tiny inline charts for latency and token usage trends.
Uses Unicode block characters: ▁▂▃▄▅▆▇█
"""
from __future__ import annotations

BARS = " ▁▂▃▄▅▆▇█"

def sparkline(values: list[float], width: int = 20) -> str:
    """Generate a sparkline string from a list of values."""
    if not values: return "(no data)"
    if len(values) == 1: return f"{values[0]:.0f}"
    mn, mx = min(values), max(values)
    if mx == mn: return BARS[4] * min(width, len(values))
    # Resample to width
    step = max(1, len(values) // width)
    sampled = [sum(values[i:i+step])/len(values[i:i+step]) for i in range(0, len(values), step)]
    sampled = sampled[:width]
    result = ""
    for v in sampled:
        idx = int((v - mn) / (mx - mn) * 8)
        result += BARS[min(idx, 8)]
    return result

def latency_sparkline(tracker=None) -> str:
    """Generate a sparkline from latency tracker data."""
    try:
        from orca_code.latency_tracker import get_latency_tracker
        lt = tracker or get_latency_tracker()
        samples = list(lt._samples)[-60:]  # Last 60 samples
        return sparkline(samples, 30)
    except: return "(no latency data)"

def tokens_sparkline(tracker=None) -> str:
    """Generate a sparkline from rate tracker token data."""
    try:
        from orca_code.rate_tracker import get_rate_tracker
        rt = tracker or get_rate_tracker()
        samples = [r.input_tokens + r.output_tokens for r in list(rt._records)[-30:]]
        return sparkline(samples, 30)
    except: return "(no token data)"
