# Changelog

## 1.0.1 — 2026-11-06

Fixes from a real run on a live MT5 **demo** account (build 6304, equity 100 000 USD).

**Bugs fixed**

- `journal` crashed with `module 'MetaTrader5' has no attribute 'history_select_range'`.
  The Python package only exposes `history_deals_get(date_from, date_to)` /
  `history_deals_total(...)`; `HistorySelectRange` is MQL5-only. `bridge.deals()` now
  calls `history_deals_get` with real datetimes.
- `doctor` printed `margin -1.00` when `order_calc_margin` returns a negative value
  (the broker could not compute it) → now prints `margin n/a (l'broker ma 7sebach)`.
- `doctor` said “klik AutoTrading” even when AutoTrading was already on → the detail
  line now shows `trade_allowed=True` when it is OK; the symbol line also shows
  `value_per_point`.
- `doctor` no longer WARNs `terminal_path not set` when the terminal that is already
  running answered fine (`not set - kansta3mlo terminal li mfto7`).

**No more silent zeroes**

- `screen` prints `N PASS / M FAIL`, groups the failures by reason, and when nothing
  passes it prints the concrete fix with your real numbers, e.g.
  `spread: US30 120 points > max 100 -> zid "max_spread_points": 145`,
  `NAS100 machi f l'terminal: mt5trader.exe symbols --search NAS`,
  `bla trend f EURUSD, XAUUSD: … "trend": "any", "sides": "buy"`.
- An empty screen **never overwrites `targets.json`** any more (“ma ktebtch
  targets.json”), so `plan` keeps working from the last good batch instead of
  silently sizing nothing.
- `analyze` prints a table (SYMBOL / PRICE / H1 / D1 / gap% / ATR / ADR / SPRD / RSI /
  STOPp) instead of a wall of JSON; `gap%` is EMA50 vs EMA200 on D1, and `|gap| <
  0.05 %` means “flat” — that is *why* a symbol has no side.
- `screen --sides buy` (or `sell`) forces a direction when you want it anyway,
  without editing JSON.
- `plan` on an empty batch tells you to run `screen --show-fails` (or the copycat
  equivalent) instead of “targets empty”.
- `calendar` says out loud that the Python package has no MT5 calendar (MQL5 only)
  and how to feed it (`trader/data/calendar.json` or `calendar_url`).

**Skills that refuse to lie**

- 0 PASS is a legitimate answer: flat D1 trend + closed market + a spread above the
  cap. The fix is a knob in `trader/rules.json`, not code that forces a side.

**App**

- The menu prints once, blank input just asks again, `h` reprints it, unknown keys say
  `ma fhemtch … (h l l'liste)`, and an error inside one command no longer kills the menu.

Tests: 149.

## 1.0.0 — 2026-11-05

First release: 12 skills on top of the MT5 Python API, bilingual Darija/English docs,
`mt5trader.exe` single entry point, demo-first with a risk gate and a per-order “yes”.
