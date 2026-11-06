---
name: mt5-alerts
description: >-
  Alerts and Session Clock. Rings once when a price level, a spread, a pip move,
  the floating P&L or the margin level crosses what you set, and keeps a state
  file so it does not nag. Also answers "is the market open", "what time is it
  at my broker", "which session are we in", "when does London open". Use when
  the user says "alert me at 1.10", "watch the spread", "tell me when gold
  moves 50 pips", "warn me if margin drops", "set a price alert", or puts
  anything on a schedule.
argument-hint: "[check|clock] [--json] [--reset]"
---

# mt5-alerts

Alerts are cheap, and a script on a schedule is the cheapest watchman there is.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py"            # check every alert
python3 "${CLAUDE_SKILL_DIR}/alerts.py" --json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock       # server time + sessions
python3 "${CLAUDE_SKILL_DIR}/alerts.py" --reset     # forget what fired
python3 "${CLAUDE_SKILL_DIR}/alerts.py" --reset-id eur-1.10
```

Exit code `1` when something fired, so a scheduler can act on it.

## trader/alerts.json

```json
{"alerts": [
  {"id": "eur-1.10", "symbol": "EURUSD", "type": "price_above", "level": 1.10, "once": true},
  {"id": "spr", "symbol": "EURUSD", "type": "spread_above", "points": 25},
  {"id": "move", "symbol": "GBPUSD", "type": "pips_move", "pips": 40, "window_min": 60},
  {"id": "mg", "type": "margin_level_below", "level": 250},
  {"id": "lon", "type": "session", "session": "london", "event": "open", "within_min": 5}
]}
```

| type | fires when |
| --- | --- |
| `price_above` / `price_below` | the mid crosses the level |
| `spread_above` / `spread_below` | the spread in points crosses the limit |
| `pips_move` | the symbol moved at least N pips inside the window |
| `margin_level_below` | the account's margin level drops under the floor |
| `floating_profit_below` / `_above` | total open P&L crosses the level |
| `session` | a session opens or closes within `within_min` |

Every alert takes `once` and `cooldown_min`; state lives in
`trader/state/alerts.json` so a re-run does not repeat itself.

## clock

```
UTC 2026-11-06 12:04 | server ~14:04 (+2.0h) | OPEN
  London   OPEN    opens in   0 min, closes in 240 min
  New York opened  ...
```

Sessions are the standard UTC windows (Sydney 21-06, Tokyo 00-09, London 07-16,
New York 12-21). Broker server time is estimated from the last tick, because
that is the clock on your charts.

## Scheduling

- Windows: Task Scheduler, `python alerts.py` every 5 minutes, "run whether
  logged on or not".
- Linux/Mac with MT5 elsewhere: run it on the Windows box, or on the snapshot.
- Ask before creating a recurring job; a wrong schedule that sends orders is
  worse than no schedule. Alerts are read-only, orders are not.

## What to say

Report only what fired, with the number that triggered it. "Nothing fired, 9
alerts checked" is a complete answer - do not invent urgency.
