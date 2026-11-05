---
name: mt5-copycat
description: >-
  Copy a Book. Turns somebody else's positions - a statement you export from
  Myfxbook, a prop firm, an old broker, a signal provider's published trades,
  or your own open positions - into target weights on the symbols YOUR broker
  lists, then compares them with what you hold. Use when the user says "copy
  this trader", "copy these positions", "resize my book", "here is my other
  account statement", "make my portfolio look like this", or before running the
  budget/risk/execute chain on someone else's idea.
argument-hint: "statement FILE | positions | manual --weights EURUSD=30,..."
---

# mt5-copycat

Copying is not a shortcut around risk. It is a way to borrow an allocation,
which then gets sized to your equity and gated by your limits, exactly like an
idea from the screener.

```bash
python3 "${CLAUDE_SKILL_DIR}/copy.py" statement source.csv --top 5 --write
python3 "${CLAUDE_SKILL_DIR}/copy.py" statement source.json --write
python3 "${CLAUDE_SKILL_DIR}/copy.py" positions --top 4 --write
python3 "${CLAUDE_SKILL_DIR}/copy.py" manual --weights EURUSD=30,GBPUSD=25,XAUUSD=20 --write
python3 "${CLAUDE_SKILL_DIR}/copy.py" diff
```

## The three sources

**statement** - a CSV with a header `symbol,side,volume` (price optional), or a
JSON `{"positions": [{"symbol": "EURUSD", "side": "buy", "volume": 0.5}]}`.
Semicolon separators, extra columns and lowercase all work.

**positions** - your own open book, renormalised. Useful for "keep the shape,
shrink the risk", and for copying an account you already traded by hand.

**manual** - weights you type. Fastest, and the only one where you can explain
every number.

## What it does with the source

1. maps every symbol to your broker's own name, suffix included
   (`XAUUSD.raw`, `EURUSDm`, `GER40` vs `DE40`)
2. drops anything your broker does not list, and says which ones it dropped
3. weights by notional when a price is given, by lots otherwise
4. renormalises to 100 over what survives, keeps `--top N`
5. writes `trader/targets.json` - the same contract mt5-screener writes

`diff` compares the targets against your open positions: to open, to close, to
check the side.

## What it never does

- it does not open an account with the source, does not read their API, and
  does not touch their money; it reads a file the user gave you
- it does not send an order - mt5-budget sizes, mt5-risk gates, mt5-broker asks
- it does not silently invert shorts: `side` in the target is the direction YOU
  take, and mt5-risk blocks shorts if `allow_short` is false

## The thing to say out loud

A 13F-style book is a snapshot of what somebody held, not what they hold now,
and their position size reflects their equity, not yours. Copy the shape,
never the lots.
