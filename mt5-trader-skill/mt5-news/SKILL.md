---
name: mt5-news
description: >-
  Headline Monitor. Pulls RSS feeds and keeps only the items that name your
  currencies, your symbols or the phrases that move FX (Fed, ECB, CPI, NFP,
  rate decision, tariffs, intervention), tags each one with what it matched and
  a severity guess, and writes trader/news.json. Use when the user says "what is
  moving the market", "any news on gold", "why is the euro jumping", "headlines
  for my pairs", or on a schedule next to /mt5-calendar.
argument-hint: "[--hours 24] [--symbols EURUSD XAUUSD] [--write]"
---

# mt5-news

RSS only: no key, no signup, no scraping, and a dead feed is skipped instead of
crashing the run.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py" --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --currencies USD,EUR --write
python3 "${CLAUDE_SKILL_DIR}/news.py" --symbols XAUUSD --json
python3 "${CLAUDE_SKILL_DIR}/news.py" --offline     # trader/data/news.json
```

## What it reads

| input | what |
| --- | --- |
| `trader/config.json` | `news_feeds`, `news_currencies` |
| `trader/symbols.json` | your universe, mapped to currencies |
| feeds | any RSS 2.0 or Atom URL, including your broker's own news feed |

## How it filters

Each item is scored by the words it contains:

- **currencies** - "euro", "ECB", "Lagarde" for EUR; "dollar", "Fed", "FOMC",
  "Powell" for USD; and so on for GBP, JPY, CHF, AUD, NZD, CAD, CNY, XAU
- **symbols** - the ticker itself
- **severity** - `high` for crash/plunge/war/default/intervention/rate
  decision words, `medium` for CPI/payrolls/GDP/tariffs, else `low`

Items that match nothing are dropped, not summarised. `feed_errors` tells you
which feed failed and why, so a silent empty list is never a mystery.

## The rule for the chat

- A headline is context, not a signal. Never let it become an order without the
  full chain: budget, risk, your yes.
- Quote the headline and its time; do not paraphrase it into a claim.
- If the item is scheduled (NFP, CPI), it belongs in mt5-calendar as a blackout,
  not here as a story.
- `--offline` reads a snapshot, which is how the tests and a laptop without
  network still work.
