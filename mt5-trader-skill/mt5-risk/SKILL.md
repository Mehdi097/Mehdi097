---
name: mt5-risk
description: >-
  Risk Gate. Checks every proposed MT5 order against your limits and the live
  account and returns PASS or BLOCK with the reasons: kill switch, real account
  without allow_live, daily loss, drawdown, margin level, blocked or allowed
  symbols, spread, news blackout, volume and lot step, total lots, risk per
  trade, missing or invalid stop, reward:risk, margin, duplicate positions,
  daily order cap. Writes trader/state/risk.json with a fingerprint per order.
  Use when the user says "check these orders", "is this safe", "risk check",
  "what would break my rules", or before /mt5-broker, always.
argument-hint: "[path to orders.json]"
---

# mt5-risk

The gate between a plan and the market. A BLOCK is final for that order: the
broker skill will not show it as READY, and no yes changes that. Fix the order
and re-run the gate.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                # trader/orders.json, writes verdicts
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write     # look, record nothing
python3 "${CLAUDE_SKILL_DIR}/check.py" --orders other.json
```

Exit code: `0` every order passed, `1` something was blocked, `2` could not run.

## What it reads

| file | what |
| --- | --- |
| `trader/orders.json` | the proposals from mt5-budget or mt5-exposure |
| `trader/config.json` | every limit |
| `trader/calendar.json` | blackout windows from mt5-calendar (optional) |
| `trader/state/broker.json` | what was sent today, for duplicates and the cap |
| `trader/state/equity_peak.json` | the high-water mark for drawdown |
| MT5 / snapshot | account, free margin, positions, today's closed deals |

## The global gates (they block every order at once)

| gate | blocks when |
| --- | --- |
| kill switch | `trader/state/KILL` exists |
| real account | `is_real` and `allow_live` is not true |
| daily loss | closed P&L today plus floating loss >= `max_daily_loss_pct` |
| drawdown | equity is `max_drawdown_pct` under the recorded peak |
| margin level | the account's margin level is under `min_margin_level_pct` |
| order cap | `max_orders_per_day` already sent today |

## The per-order checks

symbol list, quote present, spread cap, volume > 0, on the lot step, within
`volume_min`/`volume_max`, `max_lots_per_order`, `max_total_lots` including
open positions, SL required and on the correct side and outside the broker's
stops level, reward:risk, risk per trade in money and %, margin needed versus
free margin and the margin level after the fill, one position per symbol,
duplicates in the batch, the same order already sent today, the same UTC hour
blocked in config.

## What it writes

`trader/state/risk.json`: every result with `order_id`, `fingerprint`,
`verdict`, `reasons`, `checks` (price, spread, SL/TP pips, risk money and %,
margin, margin level after, reward:risk) and the exact order it judged. The
fingerprint is the sha of the order's symbol, side, type, volume, price, SL, TP,
magic and deviation, so mt5-broker can only ever send an order that passed this
gate today.

## The rule for the chat

Say "BLOCKED" and the reason in one line, never "should be fine". If the user
wants to trade anyway, the answer is: change the limit in `config.json`
deliberately, re-run the gate, and see it pass. Do not edit
`trader/state/risk.json` by hand - it is the record.
