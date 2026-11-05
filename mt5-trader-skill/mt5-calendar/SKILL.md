---
name: mt5-calendar
description: >-
  Economic Calendar and News Blackout. Lists the high-impact releases for the
  currencies you trade (NFP, CPI, FOMC, ECB, BoE, BoJ, rate decisions) for the
  next hours, turns them into blackout windows around the release, writes
  trader/calendar.json, and answers "am I inside a blackout right now". mt5-risk
  reads that file and blocks orders inside the window. Use when the user says
  "is there news today", "when is NFP", "can I trade now", "blackout", "should
  I open before the ECB", or before any entry on a volatile day.
argument-hint: "[--hours 48] [--mine] [--write] [--check EURUSD]"
---

# mt5-calendar

The stop you place is not the stop you get when a rate decision prints. This
skill is the one that says "not now".

```bash
python3 "${CLAUDE_SKILL_DIR}/econ.py" --mine --hours 48
python3 "${CLAUDE_SKILL_DIR}/econ.py" --write          # -> trader/calendar.json
python3 "${CLAUDE_SKILL_DIR}/econ.py" --check EURUSD   # exit 1 = in a blackout
python3 "${CLAUDE_SKILL_DIR}/econ.py" --impact high --minutes 45 --json
```

## Where the events come from

1. **MT5's own calendar** - `calendar_events_by_country_get` if your build of
   the package exposes it and the terminal is connected.
2. **a snapshot** - `trader/data/calendar.json`, whatever you dropped there or
   what this script wrote last time.
3. **a URL** - `"calendar_url"` in config.json returning `{"events": [...]}`.

If none answers, it says `source: none` and writes nothing. It never invents
an event, and it never blocks a trade on a guess.

## The blackout

`news_blackout_minutes` (default 30) on each side of a high-impact event, for
the currencies that event belongs to:

```
USD Nonfarm Payrolls 13:30Z  ->  blackout 13:00Z - 14:00Z for USD pairs
```

`trader/calendar.json` holds both the events and the windows; mt5-risk reads
the windows and blocks any order whose symbol touches that currency. The
`--check SYMBOL` exit code makes it usable in a shell pipeline or before an
execute call.

## How to say it

- "USD payrolls in 40 minutes, I would not open this now" beats a lecture.
- Give the time in the user's own clock as well as UTC when you can.
- A blackout is not a reason to close a position - it is a reason not to open
  one, and a reason to have the stop already in place.
