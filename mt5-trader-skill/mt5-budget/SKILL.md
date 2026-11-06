---
name: mt5-budget
description: >-
  Position Sizer. Turns target weights into real lot sizes and exact SL/TP
  prices from each symbol's own contract spec (tick value, contract size, lot
  step, stops level), respects a portfolio risk budget, a per-trade risk cap,
  the broker's minimum lot and your free margin, and writes trader/orders.json
  as proposals. Use when the user says "size these trades", "how many lots",
  "with 0.5% risk on a 25 pip stop", "what is my position size", "budget my
  account", or after /mt5-screener or /mt5-copycat.
argument-hint: "[--risk 0.5] [--equity 5000] [--fixed-lot 0.1]"
---

# mt5-budget

The step where an idea becomes money risked. It never sends anything.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                     # the plan, writes nothing
python3 "${CLAUDE_SKILL_DIR}/size.py" --write             # -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --risk 0.25 --write
python3 "${CLAUDE_SKILL_DIR}/size.py" --offline --equity 5000 --json
python3 "${CLAUDE_SKILL_DIR}/size.py" --fixed-lot 0.01 --write
```

## The arithmetic, in order

1. **risk budget** `portfolio_risk_pct` (default 3%) is the most the whole book
   may lose if every stop is hit. Each idea gets a share of it by weight.
2. **per-trade cap** nothing risks more than `max_risk_pct_per_trade` (1%).
   One idea at 60% weight cannot become a 1.8% trade.
3. **stop first, lot second** the SL distance is decided first (from the
   target, or `default_stop_pips`), then
   `lots = risk_money / (SL points x value_per_point)`.
   Wider stop, smaller lot, same money at risk. That is the whole trick.
4. **broker minimum** if `volume_min` would risk more than the cap, the trade is
   **SKIPPED with the number**, not rounded up. `allow_min_lot` overrides, with
   a warning line in the output saying the real risk.
5. **lot ceilings** `max_lots_per_order`, then `max_total_lots` across the
   batch, scaled down proportionally, never up.
6. **margin** the batch is trimmed from the end until it fits free margin while
   keeping `min_margin_level_pct`.

## What it writes

`trader/orders.json`:

```json
{"equity": 9989.15, "currency": "USD", "risk_budget_pct": 3.0,
 "total_lots": 0.87, "margin_used": 940.12,
 "orders": [{"id": "EURUSD-buy-20261106120000", "symbol": "EURUSD", "side": "buy",
             "type": "market", "volume": 0.24, "sl": 1.07790, "tp": 1.08790,
             "stop_pips": 20.0, "risk_pct": 0.6, "risk_money": 48.0,
             "reward_risk": 2.0, "magic": 20261106, "comment": "mt5-budget 0.6%"}],
 "skipped": [{"symbol": "US30", "reason": "..."}]}
```

`skipped` is not a failure, it is information: the reason is printed with the
numbers so the user can decide to widen the budget, not the risk.

## Things to say instead of guessing

- The account currency and the symbol's profit currency differ: the pack
  assumes it can use the symbol's own tick value, and says so.
- `equity` is used, not `balance`, when they differ.
- A quote of 0 means the market is closed. The target is skipped, not priced.
- Never hand-edit `volume` in orders.json afterwards. Re-run with `--risk` or
  change the stop, so the SL and the lot stay consistent.
