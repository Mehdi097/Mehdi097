---
name: mt5-analyst
description: >-
  Symbol Analyst. Reads bars and quotes from MT5 and writes one row per symbol
  to trader/metrics.json: ATR and ADR in pips, RSI, the EMA trend on H1 and D1,
  where today's range sits against its 20-day history, the spread now versus
  the average you pay, swaps, and a suggested stop and target. Use when the
  user says "what is EURUSD doing", "how volatile is gold", "give me the ATR",
  "analyse these pairs", "is this symbol worth trading", or before
  /mt5-screener and /mt5-budget.
argument-hint: "[SYMBOL ...]"
---

# mt5-analyst

The analyst does not predict. It measures, so the next skill can size.

```bash
python3 "${CLAUDE_SKILL_DIR}/analyst.py"                       # whole universe
python3 "${CLAUDE_SKILL_DIR}/analyst.py" EURUSD XAUUSD --json
python3 "${CLAUDE_SKILL_DIR}/analyst.py" --offline --write      # -> trader/metrics.json
```

## What it reads

| file | what |
| --- | --- |
| `trader/symbols.json` | the universe (or pass symbols on the command line) |
| `trader/config.json` | `stop_atr_multiple`, `min_reward_risk`, `default_stop_pips` |
| MT5 / snapshot | H1 and D1 bars, tick, symbol spec |

## What it writes

`trader/metrics.json`, one block per symbol:

| field | meaning |
| --- | --- |
| `atr_h1_pips`, `atr_d1_pips` | average true range, Wilder, in pips |
| `adr20_pips` | average daily range of the last 20 days |
| `rsi_h1` | RSI(14) on H1 |
| `trend_h1`, `trend_d1` | up / down / flat, from the EMA stack |
| `ema_slope_d1_pct` | how fast the daily trend is moving, in % over 10 bars |
| `today_range_pctile` | today's range as a percentile of the last 20 days |
| `spread_points`, `avg_spread_points` | what you pay now, and usually |
| `swap_long`, `swap_short` | the carry, per lot per night |
| `suggested_stop_pips`, `suggested_tp_pips` | ATR x multiple, and x reward:risk |
| `suggested_sl_price_buy`, `suggested_sl_price_sell` | the same in price, on the current quote |

## How to read it

- ATR is the honest unit of "how far can it go". A 20-pip stop on a symbol
  with a 90-pip ATR is noise, not a stop.
- `spread_points` against `atr_h1_pips` is the cost of the idea: a 25-point
  spread on an 8-pip ATR means the broker eats the trade.
- `trend_d1` and `trend_h1` disagreeing is a range, not a trend.
- Percentile near 100 means today already moved more than usual: chasing here
  pays for someone else's exit.

## Notes

- Standard-library indicators, so the numbers match a hand calculation and do
  not drift with a library upgrade.
- `--offline` reads `trader/data/snapshot.json`, so the same report can be
  produced from a laptop without a terminal.
- If a symbol errors (wrong name, market closed), the row keeps the error and
  the rest of the universe still gets analysed.
