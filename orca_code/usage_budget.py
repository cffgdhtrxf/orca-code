"""orca_code.usage_budget — API usage budget tracking (P2-80).

Track token/cost usage against daily/weekly budgets. Warn when approaching limits.
Config: {"budget": {"daily_tokens": 100000, "daily_cost": 1.00, "warn_at": 0.8}}
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from orca_code.cost_estimator import estimate_cost


class UsageBudget:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        b = cfg.get("budget", {})
        self.daily_tokens = b.get("daily_tokens", 0)
        self.daily_cost = b.get("daily_cost", 0.0)
        self.warn_at = b.get("warn_at", 0.8)
        self._tokens_today = 0
        self._cost_today = 0.0
        self._lock = threading.Lock()
        self._load()
    def _load(self):
        try:
            p = Path.home() / ".orca" / "budget.json"
            if p.exists():
                d = json.loads(p.read_text())
                self._tokens_today = d.get("tokens", 0)
                self._cost_today = d.get("cost", 0.0)
        except: pass
    def _save(self):
        try:
            p = Path.home() / ".orca" / "budget.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"tokens": self._tokens_today, "cost": round(self._cost_today, 4)}))
        except: pass
    def record(self, model: str, input_tokens: int, output_tokens: int):
        with self._lock:
            self._tokens_today += input_tokens + output_tokens
            c = estimate_cost(model, input_tokens, output_tokens)
            self._cost_today += c["total_cost"]
            self._save()
    def check(self) -> dict:
        with self._lock:
            tok_pct = self._tokens_today / max(self.daily_tokens, 1)
            cost_pct = self._cost_today / max(self.daily_cost, 0.001)
            return {
                "tokens_used": self._tokens_today, "tokens_limit": self.daily_tokens,
                "tokens_pct": round(tok_pct * 100, 1),
                "cost_used": round(self._cost_today, 4), "cost_limit": self.daily_cost,
                "cost_pct": round(cost_pct * 100, 1),
                "warning": tok_pct >= self.warn_at or cost_pct >= self.warn_at,
                "exceeded": tok_pct >= 1.0 or cost_pct >= 1.0,
            }
    def format(self) -> str:
        c = self.check()
        return f"Budget: {c['tokens_used']:,}/{c['tokens_limit']:,} tokens ({c['tokens_pct']}%) | ${c['cost_used']:.3f}/${c['cost_limit']:.2f} ({c['cost_pct']}%)"

_budget: UsageBudget | None = None
def get_budget() -> UsageBudget:
    global _budget
    if _budget is None:
        from orca_code.config import CONFIG
        _budget = UsageBudget(CONFIG)
    return _budget
