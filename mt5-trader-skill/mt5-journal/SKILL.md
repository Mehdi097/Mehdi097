---
name: mt5-journal
description: >-
  Trade Journal. Reads MT5's own deal history and turns it into closed trades
  and the numbers that matter: net, win rate, profit factor, expectancy, average
  win and loss, streaks, max drawdown of the equity curve, average holding time,
  and the breakdown by symbol, hour, weekday and magic number. Use when the user
  says "how am I doing", "my stats", "win rate", "show my trades", "what is my
  drawdown", "which symbol loses me money", or at the end of a week or month.
argument-hint: "[--days 30] [--symbol EURUSD] [--trades]"
---

# mt5-journal

No opinions, no dashboards. The terminal already recorded every deal; this
reads it and does the arithmetic.

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" --days 30
python3 "${CLAUDE_SKILL_DIR}/journal.py" --days 90 --json
python3 "${CLAUDE_SKILL_DIR}/journal.py" --symbol EURUSD --trades
python3 "${CLAUDE_SKILL_DIR}/journal.py" --days 30 --write   # -> trader/state/journal.json
python3 "${CLAUDE_SKILL_DIR}/journal.py" --offline
```

## How a trade is counted

Deals with `entry = IN` open a position, `entry = OUT` close it. Deals are
grouped by `position_id`; a group counts only when the closed volume covers the
opened volume, so partial closes never invent a trade. P&L is
`profit + commission + swap` - exactly the account history line.

## The numbers, and what they mean

| number | how to read it |
| --- | --- |
| `net` | what the account actually did over the window |
| `win_rate` | meaningless alone: 80% at RR 0.3 loses money |
| `profit_factor` | gross win / gross loss. Under 1.2 is fragile |
| `expectancy` | average per trade. This x trades is the month |
| `max_drawdown` | the deepest hole in the closed-trade curve |
| `max_loss_streak` | how many in a row you must sit through |
| `avg_duration_min` | scalping or swing, in numbers |
| `commission`, `swap` | the part of the loss you cannot trade away |

`by_symbol`, `by_hour`, `by_weekday` and `by_magic` find where the edge is and
where it is only fees.

## The honest read for the chat

- Report the window and the number of trades with the result. Eight trades is
  a story, not statistics.
- Compare expectancy before and after commission and swap.
- If the drawdown is bigger than the risk plan assumed, the sizing was too
  aggressive - say it plainly.
- Open floating P&L is shown separately and never mixed into closed stats.
