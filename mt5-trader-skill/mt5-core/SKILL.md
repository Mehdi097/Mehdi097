---
name: mt5-core
description: >-
  MT5 Link. The one part of this pack that talks to MetaTrader 5: connection
  mode (live terminal or offline snapshot), account summary, symbol specs
  (digits, tick value, contract size, lot step, stops level, filling mode),
  quotes, bars, open positions, margin and closing a position. Use it first on
  a new machine, and whenever the user asks "am I connected", "what is my
  balance", "what is the tick value of XAUUSD", "which symbol name does my
  broker use", "close that position". Also holds doctor.py, which answers
  "is this machine ready to trade from python".
argument-hint: "[doctor|account|spec SYMBOL|tick SYMBOL|positions|symbols --search XAU]"
---

# mt5-core

Everything else in the pack is arithmetic on JSON. This folder is the wire to
the terminal, so it is the only place where a mistake reaches the broker.

Set it up once. Then every other skill finds it automatically by looking for a
sibling `mt5-core/` folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/doctor.py" --init --write   # checklist + creates trader/
python3 "${CLAUDE_SKILL_DIR}/bridge.py" doctor            # connect, symbol lookup
python3 "${CLAUDE_SKILL_DIR}/bridge.py" account --json
python3 "${CLAUDE_SKILL_DIR}/bridge.py" spec XAUUSD --json
python3 "${CLAUDE_SKILL_DIR}/bridge.py" symbols --search XAU
python3 "${CLAUDE_SKILL_DIR}/bridge.py" snapshot --write  # offline copy of what it sees
python3 "${CLAUDE_SKILL_DIR}/bridge.py" close 50123456
```

## The two modes

| mode | what it does | when |
| --- | --- | --- |
| `live` | the `MetaTrader5` python package drives your running terminal | the real thing, Windows |
| `offline` | reads `trader/data/snapshot.json`, sends nothing | tests, a Mac/Linux laptop, reviewing a plan |

`"mode": "auto"` (the default) picks live when the package is installed, and
offline when it is not and a snapshot exists. `--offline` / `--live` force it.

## Credentials

Never in JSON, never in the chat. Environment variables only:

```
MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH
```

The config holds the terminal path, the magic number, the deviation and the
symbol suffix. Nothing else.

## What every other skill reads from here

`spec()` returns one consistent dict per symbol, whatever the instrument is:

```
digits point pip tick_size tick_value value_per_point contract_size
volume_min volume_max volume_step stops_level_points freeze_level_points
spread_points filling_mode_mask currency_base currency_profit swap_long swap_short
```

That dict is why the sizing in mt5-budget works on EURUSD, XAUUSD, US30 and
BTCUSD without a single hard-coded pip value.

## Safety rails in this file

- `KILL` file in `trader/state/` makes `send()` refuse, permanently, until removed
- a real account is refused at send time unless `allow_live` is true and `--live` is passed
- pending orders use `ORDER_FILLING_RETURN`; market orders try the symbol's own
  supported modes, then fall back, and requotes retry with a fresh price
- every request is built from the live tick and the symbol's digits, never from
  a price the model remembered
