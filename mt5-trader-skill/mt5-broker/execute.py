#!/usr/bin/env python3
"""execute.py - the only file in this pack that can place a real MT5 order.

Four gates, every order, every time:

  1. mt5-risk said PASS for THIS exact order today (fingerprint match).
  2. You typed an explicit yes for THIS order id, in the chat, one order at a
     time. "yes to all", "ok", "sure" are refused by design.
  3. The kill switch file trader/state/KILL is absent.
  4. The account is not real, or config has "allow_live": true and you pass
     --live on the command.

    python3 execute.py show                   # tickets, READY or not
    python3 execute.py show --json
    python3 execute.py approve --id EURUSD-buy-... --reply "yes"
    python3 execute.py decline --id EURUSD-buy-... --reply "no"
    python3 execute.py send --id EURUSD-buy-...          # demo account
    python3 execute.py send --id EURUSD-buy-... --live   # real account, explicit
    python3 execute.py close --ticket 12345678 --reply "yes"
    python3 execute.py close-all --reply "yes, close all 3"
    python3 execute.py status
    python3 execute.py log                    # today's decisions
    python3 execute.py kill on                # stop everything, one file
    python3 execute.py kill off

Nothing here invents a price: the request is built from the live tick and the
symbol's own spec, then dry-run with order_check before it is sent.
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys


def _core(name):
    """Import a shared mt5-core module once per process.

    Skills live in hyphenated folders, so they cannot be imported normally.
    Caching in sys.modules also means every skill shares the same Bridge class
    and the same BridgeError, so `except BridgeError` always catches.
    """
    key = "mt5core_" + name
    if key in sys.modules:
        return sys.modules[key]
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "mt5-core"), os.path.join(here, "mt5-core"),
                 os.environ.get("MT5_TRADER_CORE", ""), here):
        if not cand:
            continue
        path = os.path.join(cand, name + ".py")
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location(key, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[key] = mod
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("mt5-core/%s.py ma l9itch / not found - keep the pack folders together" % name)


bridge_mod = _core("bridge")
sizing = _core("sizing")
Bridge = bridge_mod.Bridge
BridgeError = bridge_mod.BridgeError

FINGERPRINT_FIELDS = ("symbol", "side", "type", "volume", "price", "sl", "tp", "magic", "deviation")

YES_WORDS = ("yes", "yeah", "yep", "y", "wah", "wa", "iyyeh", "na3am", "safi", "ok", "okay")
BATCH_WORDS = ("all", "every", "everything", "both", "them", "rest", "batch", "koulhom",
               "kolhom", "kolchi", "kollhom", "each", "and", "plus", "also")
DOUBT_WORDS = ("no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe",
               "later", "hold", "unless", "if", "except", "la", "machi", "mazal", "ba9i")


class ExecError(Exception):
    pass


def fingerprint(order):
    payload = {}
    for field in FINGERPRINT_FIELDS:
        value = order.get(field)
        if isinstance(value, float):
            value = round(value, 6)
        payload[field] = value
    import hashlib
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- state

def state_path(root):
    return os.path.join(root, "state", "broker.json")


def load_state(root):
    data = bridge_mod.read_json(state_path(root), {}) or {}
    if isinstance(data, list):
        data = {"decisions": data}
    data.setdefault("decisions", [])
    return data


def save_state(root, state):
    bridge_mod.write_json(state_path(root), state)


def load_orders(root, path=None):
    data = bridge_mod.read_json(path or os.path.join(root, "orders.json"), None)
    if data is None:
        raise ExecError("no orders at %s - run mt5-budget first" % (path or root + "/orders.json"))
    rows = data.get("orders", data) if isinstance(data, dict) else data
    return [o for o in rows if isinstance(o, dict)]


def load_risk(root):
    data = bridge_mod.read_json(os.path.join(root, "state", "risk.json"), None) or {}
    return data


def verdict_for(risk, order):
    if not risk or risk.get("date") != utc_today():
        return None, ["risk check dyal lyoum ma kaynch / no risk verdict from today - run mt5-risk"]
    fp = fingerprint(order)
    for row in risk.get("results") or []:
        if row.get("fingerprint") == fp:
            return row, [] if row.get("verdict") == "PASS" else row.get("reasons", [])
    return None, ["had l'order ma 3ndhach PASS lyoum / this order has no PASS from today"]


def decision_for(state, order_id):
    for row in reversed(state.get("decisions") or []):
        if row.get("order_id") == order_id and row.get("action") in ("approved", "sent", "declined"):
            return row
    return None


def is_real_yes(reply):
    text = re.sub(r"[^\w\s']", " ", (reply or "").lower()).strip()
    words = text.split()
    if not words:
        return False, "reply khawi / empty reply"
    if any(w in BATCH_WORDS for w in words):
        return False, "ma 9belch \"yes to all\" / batch words refused: yes one order at a time"
    if any(w in DOUBT_WORDS for w in words):
        return False, "fiha kelma dyal chouk / doubt word in the reply: %r" % reply
    if not any(w in YES_WORDS for w in words):
        return False, "ma kaynch \"yes\" f l'reply / no yes in %r" % reply
    if len(words) > 6:
        return False, "reply twila bzzaf / too long to be an unambiguous yes"
    return True, ""


# ---------------------------------------------------------------- views

def ticket(order, risk, state, b):
    """Plain-language ticket + the exact request this pack would send."""
    try:
        spec = b.spec(order["symbol"])
        tick = b.tick(order["symbol"])
    except BridgeError as e:
        return {"order": order, "status": "ERROR", "error": str(e)}
    side = order.get("side")
    price = order.get("price") or (tick["ask"] if side == "buy" else tick["bid"])
    request = dict(order)
    request["price"] = price if str(order.get("type", "market")) != "market" else None
    req = bridge_mod.build_request(request, spec, tick, b.cfg)
    row, reasons = verdict_for(risk, order)
    decision = decision_for(state, order.get("id"))
    status = "NOT READY"
    if row is not None and not reasons:
        status = "READY"
    elif row is not None:
        status = "BLOCKED"
    if decision and decision.get("action") == "sent":
        status = "SENT"
    elif decision and decision.get("action") == "declined":
        status = "DECLINED"
    return {
        "id": order.get("id"), "symbol": order["symbol"], "side": side,
        "type": order.get("type", "market"), "volume": order.get("volume"),
        "entry": round(float(price), int(spec.get("digits", 5))),
        "sl": order.get("sl"), "tp": order.get("tp"),
        "stop_pips": order.get("stop_pips"),
        "risk_pct": (row or {}).get("checks", {}).get("risk_pct", order.get("risk_pct")),
        "risk_money": (row or {}).get("checks", {}).get("risk_money", order.get("risk_money")),
        "reward_risk": order.get("reward_risk"),
        "status": status, "reasons": reasons if row is not None else reasons,
        "request": req, "fingerprint": fingerprint(order),
    }


def render(t):
    if t.get("status") == "ERROR":
        return "%-30s ERROR %s" % (t.get("order", {}).get("id"), t.get("error"))
    return ("%-30s %-8s %-4s %-6s %.2f lots @ %s  SL %s  TP %s  risk %s%%  RR %s\n"
            "  -> %s%s" % (
                t.get("id"), t["symbol"], t["side"], t["type"], float(t["volume"]),
                t["entry"], t["sl"], t["tp"], t["risk_pct"], t["reward_risk"],
                t["status"], "" if not t["reasons"] else "  | " + "; ".join(t["reasons"])))


# ---------------------------------------------------------------- commands

def cmd_show(b, args, state, risk, orders):
    rows = []
    for order in orders:
        t = ticket(order, risk, state, b)
        rows.append(t)
        print(render(t))
        print()
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True, default=str))
    if not rows:
        print("ma kaynch orders / no proposed orders")
    return 0


def cmd_approve(b, args, state, risk, orders):
    order = next((o for o in orders if o.get("id") == args.id), None)
    if order is None:
        raise ExecError("order id ma kaynch / no order with id %s" % args.id)
    t = ticket(order, risk, state, b)
    if t["status"] != "READY":
        raise ExecError("order %s machi READY (%s) / cannot approve: %s"
                        % (args.id, t["status"], "; ".join(t["reasons"])))
    ok, why = is_real_yes(args.reply)
    if not ok:
        raise ExecError("NO: %s" % why)
    state["decisions"].append({
        "time": bridge_mod.now_utc().isoformat(), "date": utc_today(),
        "order_id": args.id, "action": "approved", "reply": args.reply,
        "fingerprint": t["fingerprint"], "symbol": order["symbol"],
        "volume": order.get("volume"),
    })
    save_state(b.root, state)
    print("APPROVED %s - %s %s %.2f lots. Daba send: python3 execute.py send --id %s"
          % (args.id, t["symbol"], t["side"], float(t["volume"]), args.id))
    return 0


def cmd_decline(b, args, state, risk, orders):
    state["decisions"].append({
        "time": bridge_mod.now_utc().isoformat(), "date": utc_today(),
        "order_id": args.id, "action": "declined", "reply": args.reply,
    })
    save_state(b.root, state)
    print("DECLINED %s" % args.id)
    return 0


def cmd_send(b, args, state, risk, orders):
    order = next((o for o in orders if o.get("id") == args.id), None)
    if order is None:
        raise ExecError("order id ma kaynch / no order with id %s" % args.id)
    if bridge_mod.kill_switch(b.root):
        raise ExecError("KILL switch ON (trader/state/KILL). Nothing sent. "
                        "python3 execute.py kill off bach t7elha")
    t = ticket(order, risk, state, b)
    if t["status"] == "SENT":
        raise ExecError("had l'order tsift deja / already sent: %s" % args.id)
    if t["status"] != "READY":
        raise ExecError("machi READY (%s): %s" % (t["status"], "; ".join(t["reasons"])))
    approved = decision_for(state, args.id)
    if not approved or approved.get("action") != "approved":
        raise ExecError("ma kaynch yes dyalek 3la had l'order / no approval recorded: "
                        "python3 execute.py approve --id %s --reply \"yes\"" % args.id)

    acct = b.account()
    if acct.get("is_real"):
        if not b.cfg.get("allow_live", False):
            raise ExecError("compte REAL w allow_live machi true / real account, allow_live is false")
        if not args.live:
            raise ExecError("compte REAL: zid --live bach t2akked / real account: pass --live")

    req = t["request"]
    check = b.check(req)
    check_ret = int(check.get("retcode", 0) or 0)
    if check_ret not in (0, 10009):
        raise ExecError("order_check refusa / dry run failed: %s (%s)"
                        % (check_ret, check.get("comment", "")))

    if args.dry_run:
        print("DRY RUN - ma tsift walo / nothing sent. Request:")
        print(json.dumps(req, indent=2, sort_keys=True, default=str))
        print("order_check: %s" % json.dumps({k: check.get(k) for k in
                                              ("retcode", "margin", "margin_free", "comment")},
                                             sort_keys=True))
        return 0

    result = b.send(req)
    ok = bool(result.get("ok"))
    state["decisions"].append({
        "time": bridge_mod.now_utc().isoformat(), "date": utc_today(),
        "order_id": args.id, "action": "sent" if ok else "failed",
        "fingerprint": t["fingerprint"], "symbol": order["symbol"],
        "volume": req.get("volume"), "price": req.get("price"),
        "retcode": result.get("retcode"), "retcode_name": result.get("retcode_name"),
        "order_ticket": result.get("order"), "deal": result.get("deal"),
        "simulated": result.get("simulated", False),
        "comment": result.get("comment"),
    })
    save_state(b.root, state)

    journal = os.path.join(b.root, "state", "journal.jsonl")
    os.makedirs(os.path.dirname(journal), exist_ok=True)
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": bridge_mod.now_utc().isoformat(), "kind": "order",
                             "order": order, "result": {k: v for k, v in result.items()
                                                        if k != "request"}},
                            default=str) + "\n")

    if ok:
        print("SENT %s %s %.2f lots @ %s  ticket %s  retcode %s (%s)%s"
              % (order["symbol"], order["side"], float(req["volume"]),
                 req.get("price"), result.get("order"), result.get("retcode"),
                 result.get("retcode_name"),
                 "  [SIMULATED - offline]" if result.get("simulated") else ""))
        return 0
    print("FAILED %s retcode %s (%s): %s"
          % (args.id, result.get("retcode"), result.get("retcode_name"), result.get("comment")),
          file=sys.stderr)
    return 1


def cmd_close(b, args, state):
    if bridge_mod.kill_switch(b.root):
        raise ExecError("KILL switch ON - close manually in the terminal")
    ok, why = is_real_yes(args.reply)
    if not ok:
        raise ExecError("NO: %s" % why)
    positions = b.positions()
    pos = next((p for p in positions if int(p["ticket"]) == int(args.ticket)), None)
    if not pos:
        raise ExecError("position %s ma kaynch / no open position %s" % (args.ticket, args.ticket))
    if args.dry_run:
        print("DRY RUN - would close %s %s %.2f lots (profit %s)"
              % (pos["symbol"], pos["side"], float(pos["volume"]), pos["profit"]))
        return 0
    result = b.close(int(args.ticket))
    state["decisions"].append({
        "time": bridge_mod.now_utc().isoformat(), "date": utc_today(),
        "action": "closed" if result.get("ok") else "close_failed",
        "order_id": "close-%s" % args.ticket, "symbol": pos["symbol"],
        "ticket": args.ticket, "retcode": result.get("retcode"),
        "retcode_name": result.get("retcode_name"),
    })
    save_state(b.root, state)
    print("%s %s -> retcode %s (%s)" % (
        "CLOSED" if result.get("ok") else "CLOSE FAILED", args.ticket,
        result.get("retcode"), result.get("retcode_name")))
    return 0 if result.get("ok") else 1


def cmd_close_all(b, args, state):
    positions = b.positions()
    if not positions:
        print("ma kaynch positions / nothing open")
        return 0
    ok, why = is_real_yes(args.reply)
    if not ok:
        raise ExecError("NO: %s" % why)
    digits = re.findall(r"\d+", args.reply or "")
    if digits and int(digits[0]) != len(positions):
        raise ExecError("l'reply 3ndo %s, walakin 3ndak %d positions / count mismatch, "
                        "be explicit in the reply" % (digits[0], len(positions)))
    if args.dry_run:
        for p in positions:
            print("would close %s %s %s lots (profit %s)"
                  % (p["ticket"], p["symbol"], p["volume"], p["profit"]))
        return 0
    failures = 0
    for p in positions:
        result = b.close(int(p["ticket"]))
        print("%s %s %s %.2f lots -> %s (%s)" % (
            "CLOSED" if result.get("ok") else "FAILED", p["ticket"], p["symbol"],
            float(p["volume"]), result.get("retcode"), result.get("retcode_name")))
        failures += 0 if result.get("ok") else 1
    state["decisions"].append({
        "time": bridge_mod.now_utc().isoformat(), "date": utc_today(),
        "action": "close_all", "order_id": "close-all", "closed": len(positions) - failures,
        "failed": failures, "reply": args.reply,
    })
    save_state(b.root, state)
    return 0 if failures == 0 else 1


def cmd_status(b, state):
    acct = b.account()
    positions = b.positions()
    risk = load_risk(b.root)
    orders = []
    try:
        orders = load_orders(b.root)
    except ExecError:
        pass
    print("mode        : %s%s" % (b.mode, "  (no terminal)" if b.mode == "offline" else ""))
    print("account     : %s @ %s  %s" % (acct.get("login"), acct.get("server"),
                                         "REAL" if acct.get("is_real") else "demo"))
    print("balance     : %.2f %s   equity %.2f   free margin %.2f   margin level %.0f%%"
          % (float(acct.get("balance") or 0), acct.get("currency", ""),
             float(acct.get("equity") or 0), float(acct.get("margin_free") or 0),
             float(acct.get("margin_level") or 0)))
    print("positions   : %d   open lots %.2f"
          % (len(positions), sum(float(p["volume"]) for p in positions)))
    print("kill switch : %s" % ("ON" if bridge_mod.kill_switch(b.root) else "off"))
    print("pending     : %d proposed orders, %d risk PASS today"
          % (len(orders), (risk.get("counts") or {}).get("pass", 0) if risk.get("date") == utc_today() else 0))
    for w in b.warnings:
        print("warning     : %s" % w)
    return 0


def cmd_log(state, args):
    rows = state.get("decisions") or []
    if not args.all:
        rows = [r for r in rows if r.get("date") == utc_today()]
    for r in rows:
        print("%s  %-11s %-30s %s" % (r.get("time", "")[:19], r.get("action"),
                                      r.get("order_id") or "", r.get("reply") or
                                      r.get("retcode_name") or ""))
    if not rows:
        print("ma kaynch decisions / no decisions recorded")
    return 0


def cmd_kill(b, args):
    path = os.path.join(b.root, "state", "KILL")
    if args.action == "on":
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("killed %s\n" % bridge_mod.now_utc().isoformat())
        print("KILL ON - sayed l'orders m7bousin / every send is refused")
    else:
        if os.path.exists(path):
            os.remove(path)
            print("KILL OFF - l'orders t7ello / sending allowed again")
        else:
            print("KILL was already off")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="MT5 order executor: one order, one explicit yes.")
    ap.add_argument("command", choices=["show", "approve", "decline", "send", "close", "close-all",
                                        "status", "log", "kill"])
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--orders", default=None)
    ap.add_argument("--id", default=None)
    ap.add_argument("--ticket", default=None)
    ap.add_argument("--reply", default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("action", nargs="?", default="on", choices=["on", "off"])
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    try:
        state = load_state(b.root)
        risk = load_risk(b.root)
        orders = []
        try:
            orders = load_orders(b.root, a.orders)
        except ExecError:
            if a.command in ("show", "approve", "decline", "send"):
                raise
        if a.command == "show":
            return cmd_show(b, a, state, risk, orders)
        if a.command == "approve":
            if not a.id or not a.reply:
                raise ExecError("khass --id w --reply / need --id and --reply")
            return cmd_approve(b, a, state, risk, orders)
        if a.command == "decline":
            if not a.id:
                raise ExecError("khass --id / need --id")
            return cmd_decline(b, a, state, risk, orders)
        if a.command == "send":
            if not a.id:
                raise ExecError("khass --id / need --id")
            return cmd_send(b, a, state, risk, orders)
        if a.command == "close":
            if not a.ticket or not a.reply:
                raise ExecError("khass --ticket w --reply / need --ticket and --reply")
            return cmd_close(b, a, state)
        if a.command == "close-all":
            if not a.reply:
                raise ExecError("khass --reply / need --reply")
            return cmd_close_all(b, a, state)
        if a.command == "status":
            return cmd_status(b, state)
        if a.command == "log":
            return cmd_log(state, a)
        if a.command == "kill":
            return cmd_kill(b, a)
        return 2
    except (ExecError, BridgeError) as e:
        print("BROKER ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
