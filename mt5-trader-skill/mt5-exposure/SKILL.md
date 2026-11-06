---
name: mt5-exposure
description: >-
  Exposure and Rebalancer. Shows what the account is really exposed to - signed
  lots per symbol, money per point with the current net position, share of the
  book, the currency tilt (long EUR, short USD...), total money per point - then
  measures the drift against trader/targets.json and proposes the trades that
  close it. Use when the user says "what is my exposure", "am I too long
  dollar", "rebalance my portfolio", "my book drifted", "hedge check", or after
  /mt5-copycat when the targets changed.
argument-hint: "[--band 5] [--write-orders]"
---

# mt5-exposure

A trade is one position. Exposure is what happens when you have six of them.

```bash
python3 "${CLAUDE_SKILL_DIR}/rebalance.py"
python3 "${CLAUDE_SKILL_DIR}/rebalance.py" --band 5 --json
python3 "${CLAUDE_SKILL_DIR}/rebalance.py" --band 5 --write-orders
```

## The three tables

**per symbol** signed lots, share of the book, money per point with that net
position, floating P&L, and a `hedged` flag when you hold both sides.

**currency tilt** each FX pair adds its base and subtracts its quote, so
EURUSD buy 1.0 lot is +100,000 EUR and -108,000 USD (at 1.08). Normalised to
the biggest leg. Indices, metals and crypto are excluded from the tilt because
their quote is not a clean currency leg - that is the honest limit of this
measure, and the output says so.

**drift** target weight versus actual weight, per symbol, in percentage points.
With `--write-orders`, anything beyond `--band` becomes a proposed order with
SL/TP, written to `trader/orders.json`.

## The rules it keeps

- a reducing trade never proposes more than you hold
- an adding trade is sized by the notional gap, then rounded down to the lot step
- proposals go to `orders.json`, so mt5-risk still gates them and mt5-broker
  still asks for a yes
- no hedging magic: if `allow_short` is false in config, the risk gate blocks
  the sell side for you

## How to talk about it

- "You are 60% long USD across three pairs" is the sentence that matters, not
  the number of positions.
- Drift under the band is noise. Say the band and say the drift, do not
  rebalance a 2-point drift.
- Rebalancing costs spread twice. If the drift is smaller than the round trip
  cost, the right answer is to wait, and this file will not pretend otherwise.
