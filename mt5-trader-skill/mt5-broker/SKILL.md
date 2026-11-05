---
name: mt5-broker
description: >-
  Order Executor. The only skill in this pack that can place a real MetaTrader 5
  order, one at a time, only after mt5-risk passed that exact order and the user
  typed an explicit yes for it. Shows each order as a plain ticket plus the
  exact MT5 request, records the yes word for word, dry-runs with order_check,
  then sends with order_send and journals the result. Also closes positions,
  closes all, prints status and flips the kill switch. Use when the user says
  "place it", "send the order", "buy 0.1 lots", "execute", "close that
  position", "close everything", "stop trading", or after /mt5-risk.
argument-hint: "show | approve --id ID --reply yes | send --id ID | close --ticket N --reply yes | status | kill on"
---

# mt5-broker

Three gates before anything reaches the market, every time, for every order:

1. **mt5-risk passed this exact order today** - matched by fingerprint, not by
   the user's confidence.
2. **The user typed a yes for this one order id** - `approve` refuses
   "yes to all", "ok", "sure", any batch word, any doubt word ("but", "unless",
   "wait"), and anything over six words.
3. **The kill switch is off and the account gate passes** - a real account
   needs `"allow_live": true` in config **and** `--live` on the command.

```bash
python3 "${CLAUDE_SKILL_DIR}/execute.py" show
python3 "${CLAUDE_SKILL_DIR}/execute.py" approve --id EURUSD-buy-20261106120000 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/execute.py" send --id EURUSD-buy-20261106120000 --dry-run
python3 "${CLAUDE_SKILL_DIR}/execute.py" send --id EURUSD-buy-20261106120000
python3 "${CLAUDE_SKILL_DIR}/execute.py" close --ticket 50123456 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/execute.py" close-all --reply "yes, close all 2"
python3 "${CLAUDE_SKILL_DIR}/execute.py" status
python3 "${CLAUDE_SKILL_DIR}/execute.py" log --all
python3 "${CLAUDE_SKILL_DIR}/execute.py" kill on
```

## The ticket

```
EURUSD-buy-20261106120000    EURUSD   buy  market 0.24 lots @ 1.07992  SL 1.07790  TP 1.08790
  risk 0.6%  RR 2.0
  -> READY
```

Status is one of `READY`, `BLOCKED` (with the reasons), `NOT READY` (no risk
verdict today), `SENT`, `DECLINED`, `ERROR`. Only `READY` can be approved.

## What send does, in order

1. re-reads the risk verdict and the approval, by fingerprint
2. re-checks the kill switch and the account type
3. builds the request from the **live tick** and the symbol's digits, filling
   mode from `filling_mode_mask`
4. `order_check` - if the broker would refuse it, nothing is sent
5. `order_send`, with filling-mode fallback and requote retry
6. records retcode, ticket and deal in `trader/state/broker.json` and
   `trader/state/journal.jsonl`

## The script for the chat

Show the ticket. Ask for a yes for that order id. Do not paraphrase the yes,
do not approve anything the user has not seen, do not batch. After sending,
report the retcode in words: `10009 done` is filled, `10019 not enough money`
is the account, `10027 autotrading disabled` is the AutoTrading button, and
`10030 invalid filling` is the broker's filling mode (the executor already
retries the other modes once).

## Closing

`close` closes one position by ticket at market and needs a real yes.
`close-all` needs a yes that names the count when several are open. Neither is
blocked by the risk gate - closing reduces risk - but both are blocked by the
kill switch, because during an incident the terminal is the right place to act,
not a script.

## Keep the account safe

- paper/demo first: `"mode"` is about the connection, the account decides the money
- keys in environment variables only, never in config, never in chat
- set `"allow_live": false` and leave it there until the whole chain has run a
  month on demo
