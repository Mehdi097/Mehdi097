---
name: mt5-screener
description: >-
  Symbol Screener. Filters the whole universe against the user's own rules
  (minimum ATR, maximum spread, spread as a share of ATR, ADR floor, trend
  direction, reward:risk, swaps, blocked symbols), marks every symbol PASS or
  FAIL with the reason, ranks the survivors and can write trader/targets.json
  with weights. Use when the user says "which pairs should I trade today",
  "screen my watchlist", "find something with volatility and a tight spread",
  "rank these symbols", or between /mt5-analyst and /mt5-budget.
argument-hint: "[path to metrics.json]"
---

# mt5-screener

The screener turns a watchlist into a short list, using rules the user set
instead of rules the model likes.

```bash
python3 "${CLAUDE_SKILL_DIR}/screen.py"                                  # trader/ files
python3 "${CLAUDE_SKILL_DIR}/screen.py" --show-fails
python3 "${CLAUDE_SKILL_DIR}/screen.py" --trend up --top 4 --write-targets
python3 "${CLAUDE_SKILL_DIR}/screen.py" --rank-by volatility --json
```

## What it reads

| file | what |
| --- | --- |
| `trader/metrics.json` | from mt5-analyst (required) |
| `trader/rules.json` | your rules; `rules.example.json` is the starting point |

## The rules

| rule | blocks when |
| --- | --- |
| `min_atr_pips` | the symbol moves too little to pay the spread |
| `max_spread_points` | the spread right now is too wide |
| `max_spread_to_atr` | the spread eats too big a share of the move |
| `min_adr_pips` | the daily range is too small for the stops you need |
| `trend` / `timeframe` | the EMA trend disagrees with the direction you want |
| `min_reward_risk` | the suggested stop and target do not pay enough |
| `max_swap_per_lot` | holding overnight costs too much |
| `blocked_symbols` | you never want this one, whatever the data says |
| `sides` | `trend` follows the trend, or force `buy` / `sell` / `both` |

## What it writes

- the console report: PASS with weights, or FAIL with every reason it failed
- with `--write-targets`: `trader/targets.json`, weights normalised to 100,
  `stop_pips` and `tp_pips` included so mt5-budget sizes from the same numbers
  that passed the screen
- `rank_by`: `trend_strength`, `volatility`, `cost`, or `spread_vs_atr`.
  `weights`: `equal`, `volatility` or `trend_strength`.

## The honest part

A screen is a filter on the past hour and the past month. It cannot know that
a central bank speaks in twenty minutes - that is mt5-calendar's job - and it
never places anything. If everything fails, it says so and writes nothing; it
does not lower your standards to find a trade.
