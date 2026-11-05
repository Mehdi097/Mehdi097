#!/usr/bin/env python3
"""check.py - the gate. Every proposed order is PASS or BLOCK, with reasons.

Reads trader/orders.json (mt5-budget), your limits (trader/config.json), the
live account and open positions, today's activity and the calendar blackout,
then writes trader/state/risk.json. mt5-broker will only show an order as
READY if THIS exact order (same fingerprint) passed here today.

    python3 check.py                    # check trader/orders.json, write verdicts
    python3 check.py --json
    python3 check.py --no-write         # look without recording
    python3 check.py --orders other.json

What blocks an order (each one is a separate line in the report):

  global    kill switch file, real account without "allow_live", daily loss over
            the limit, drawdown over the limit, margin level under the floor,
            daily order cap already hit
  symbol    blocked list, allowed list, market closed / no quote, spread over
            the cap, news blackout for its currencies
  size      volume <= 0, not on the lot step, under volume_min or over
            volume_max, over max_lots_per_order, over max_total_lots
  risk      over max_risk_pct_per_trade, no SL while require_sl is true, SL on
            the wrong side, SL inside the broker's minimum distance,
            reward:risk under min_reward_risk
  account   would drop free margin under min_margin_level_pct, or needs margin
            this account does not have
  repeat    the same symbol already has an open position (max_positions_per_symbol),
            is already in this batch, or the same order went out today
  pending   pending order while "allow_pending" is false, or a pending order
            without a price

Exit 0 when every order passes, 1 when any order is blocked.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
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
    # A PyInstaller build unpacks the pack into sys._MEIPASS (onefile) or next to
    # mt5trader.exe (onedir). Search those first, then the normal checkout.
    bundle = getattr(sys, "_MEIPASS", None)
    if not bundle and getattr(sys, "frozen", False):
        bundle = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [os.path.join(here, "..", "mt5-core"), os.path.join(here, "mt5-core"),
                  os.environ.get("MT5_TRADER_CORE", ""), here]
    if bundle:
        candidates[:0] = [os.path.join(bundle, "mt5-core"),
                          os.path.join(bundle, "..", "mt5-core")]
    for cand in candidates:
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


class RiskError(Exception):
    pass


def fingerprint(order):
    payload = {}
    for field in FINGERPRINT_FIELDS:
        value = order.get(field)
        if isinstance(value, float):
            value = round(value, 6)
        payload[field] = value
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def parse_day(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).strftime("%Y-%m-%d")
    return str(value)[:10]


def load_positions_value(b, sym):
    try:
        spec = b.spec(sym)
    except BridgeError:
        return 0.0
    return sizing.value_per_point(spec)


# ---------------------------------------------------------------- global gates

def global_blocks(b, cfg, orders, state, trades_today):
    """Reasons that stop EVERY order in the batch."""
    reasons = []
    if bridge_mod.kill_switch(b.root):
        reasons.append("KILL switch: trader/state/KILL kayn - kolchi m7bous / kill switch is on")
    acct = b.account()
    if acct.get("is_real") and not cfg.get("allow_live", False):
        reasons.append("compte REAL w \"allow_live\" machi true / real account but allow_live is not true")
    if not acct.get("trade_allowed", True):
        reasons.append("l'account ma msmo7ch lih trading / trading not allowed on this account")

    equity = float(acct.get("equity") or 0.0)
    balance = float(acct.get("balance") or 0.0)
    currency = acct.get("currency") or cfg.get("account_currency") or "USD"

    # daily loss: closed P&L today plus floating, as a % of balance
    lost = -sum(float(t.get("profit") or 0) for t in trades_today)
    floating = sum(float(p.get("profit") or 0) for p in b.positions())
    day_loss_pct = 0.0
    if balance > 0:
        day_loss_pct = (lost - min(floating, 0.0)) / balance * 100.0
    max_daily = float(cfg.get("max_daily_loss_pct") or 0)
    if max_daily and day_loss_pct >= max_daily:
        reasons.append("daily loss %.2f%% >= limit %.2f%% / limite dyal lyoum wsel" %
                       (day_loss_pct, max_daily))

    # drawdown from the peak equity we have seen
    peak_path = os.path.join(b.root, "state", "equity_peak.json")
    peak = bridge_mod.read_json(peak_path, {}) or {}
    peak_equity = float(peak.get("peak_equity") or 0.0)
    if equity > peak_equity:
        peak_equity = equity
        bridge_mod.write_json(peak_path, {"peak_equity": round(peak_equity, 2),
                                          "updated": bridge_mod.now_utc().isoformat()})
    max_dd = float(cfg.get("max_drawdown_pct") or 0)
    dd_pct = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0
    if max_dd and dd_pct >= max_dd:
        reasons.append("drawdown %.2f%% >= limit %.2f%% (peak %.2f, equity %.2f)" %
                       (dd_pct, max_dd, peak_equity, equity))

    margin_level = float(acct.get("margin_level") or 0.0)
    floor = float(cfg.get("min_margin_level_pct") or 0)
    if floor and margin_level and margin_level < floor:
        reasons.append("margin level %.0f%% < floor %.0f%%" % (margin_level, floor))

    sent_today = [r for r in (state.get("decisions") or [])
                  if r.get("date") == utc_today() and r.get("action") == "sent"]
    cap = int(cfg.get("max_orders_per_day") or 0)
    if cap and len(sent_today) >= cap:
        reasons.append("daily order cap: %d orders already sent today (max %d)"
                       % (len(sent_today), cap))
    return reasons, {"equity": equity, "balance": balance, "currency": currency,
                     "day_loss_pct": round(day_loss_pct, 3), "drawdown_pct": round(dd_pct, 3),
                     "margin_level": margin_level, "orders_sent_today": len(sent_today)}


# ---------------------------------------------------------------- per order

def check_order(b, cfg, order, ctx):
    """Return (verdict, reasons, checks) for one order."""
    reasons, checks = [], {}
    sym = str(order.get("symbol") or "").upper()
    side = str(order.get("side") or "").lower()
    otype = str(order.get("type") or "market").lower()
    acct = ctx["account"]
    equity = float(acct.get("equity") or 0.0)
    open_positions = ctx["positions"]

    if not sym:
        return "BLOCK", ["symbol khawi / no symbol"], checks
    if side not in ("buy", "sell"):
        return "BLOCK", ["side khass buy wla sell, machi %r" % side], checks
    if otype not in ("market", "limit", "stop", "stop_limit"):
        return "BLOCK", ["order type ma3roufch / unknown type %r" % otype], checks

    # lists
    blocked = [s.upper() for s in (cfg.get("blocked_symbols") or [])]
    allowed = [s.upper() for s in (cfg.get("allowed_symbols") or [])]
    if sym in blocked:
        reasons.append("%s blocked f config / symbol is blocked" % sym)
    if allowed and sym not in allowed:
        reasons.append("%s machi f l'allowed list / symbol not in allowed_symbols" % sym)

    # quote and spec
    try:
        spec = b.spec(sym)
        tick = b.tick(sym)
    except BridgeError as e:
        return "BLOCK", [str(e)], checks
    price = float(tick.get("ask") if side == "buy" else tick.get("bid"))
    if price <= 0:
        return "BLOCK", ["%s: bid/ask = 0, market msdoud / no quote" % sym], checks
    digits = int(spec.get("digits", 5))
    checks["price"] = round(price, digits)
    checks["spread_points"] = tick.get("spread_points")

    spread_cap = int(cfg.get("max_spread_points") or 0)
    if spread_cap and otype == "market" and int(tick.get("spread_points") or 0) > spread_cap:
        reasons.append("spread %s points > max %d" % (tick.get("spread_points"), spread_cap))

    # volume
    volume = order.get("volume")
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        return "BLOCK", ["volume machi ra9m / volume is not a number: %r" % (volume,)], checks
    vmin = float(spec.get("volume_min") or 0.01)
    vmax = float(spec.get("volume_max") or 100.0)
    step = float(spec.get("volume_step") or 0.01)
    checks["volume"] = volume
    checks["volume_min"] = vmin
    checks["volume_step"] = step
    if volume <= 0:
        reasons.append("volume 0 / nothing to send")
    if volume < vmin - 1e-9:
        reasons.append("volume %.4f < volume_min %.4f" % (volume, vmin))
    if volume > vmax + 1e-9:
        reasons.append("volume %.4f > volume_max %.4f" % (volume, vmax))
    steps = volume / step if step else 0
    if step and abs(steps - round(steps)) > 1e-6:
        reasons.append("volume %.4f machi 3la lot step %.4f / not on the lot step" % (volume, step))
    max_order = float(cfg.get("max_lots_per_order") or 0)
    if max_order and volume > max_order + 1e-9:
        reasons.append("volume %.4f > max_lots_per_order %.4f" % (volume, max_order))

    already_lots = sum(float(p.get("volume") or 0) for p in open_positions) + ctx["lots_in_batch"]
    max_total = float(cfg.get("max_total_lots") or 0)
    if max_total and already_lots + volume > max_total + 1e-9:
        reasons.append("total lots %.2f + %.2f > max_total_lots %.2f"
                       % (already_lots, volume, max_total))

    # stops
    sl = order.get("sl")
    tp = order.get("tp")
    sl = float(sl) if sl not in (None, "", 0, 0.0) else None
    tp = float(tp) if tp not in (None, "", 0, 0.0) else None
    require_sl = bool(cfg.get("require_sl", True))
    if require_sl and sl is None:
        reasons.append("bla SL w require_sl = true / no stop loss")
    if sl is not None or tp is not None:
        ok, issues, sl_dist, tp_dist = sizing.stops_ok(spec, side, price, sl, tp,
                                                       tick.get("spread_points") or 0)
        checks["sl_pips"] = round(sizing.price_to_pips(spec, sl_dist), 1) if sl else None
        checks["tp_pips"] = round(sizing.price_to_pips(spec, tp_dist), 1) if tp else None
        if not ok:
            reasons.extend(issues)
        if sl and tp:
            rr = sizing.reward_risk(price, sl, tp)
            checks["reward_risk"] = rr
            min_rr = float(cfg.get("min_reward_risk") or 0)
            if min_rr and rr is not None and rr + 1e-9 < min_rr:
                reasons.append("reward:risk %.2f < min %.2f" % (rr, min_rr))

    # money at risk
    if sl is not None:
        try:
            per_lot = sizing.loss_per_lot(spec, abs(price - sl))
            risk_money = per_lot * volume
            risk_pct = risk_money / equity * 100.0 if equity > 0 else 999.0
            checks["risk_money"] = round(risk_money, 2)
            checks["risk_pct"] = round(risk_pct, 3)
            cap = float(cfg.get("max_risk_pct_per_trade") or 0)
            if cap and risk_pct > cap + 1e-6:
                reasons.append("risk %.2f%% > max %.2f%% (%.2f %s)"
                               % (risk_pct, cap, risk_money, acct.get("currency", "")))
        except sizing.SizingError as e:
            reasons.append("ma 9dertch n7seb l'risk / cannot size risk: %s" % e)

    # pending
    if otype != "market":
        if not cfg.get("allow_pending", True):
            reasons.append("pending orders m7bousin / allow_pending is false")
        if not order.get("price"):
            reasons.append("pending order bla price / pending order needs a price")

    # duplicates and counts
    per_symbol_cap = int(cfg.get("max_positions_per_symbol") or 0)
    same_symbol = [p for p in open_positions if p.get("symbol") == sym]
    if per_symbol_cap and len(same_symbol) + ctx["symbol_in_batch"].get(sym, 0) >= per_symbol_cap:
        reasons.append("%s: already %d position(s) open (max %d per symbol)"
                       % (sym, len(same_symbol), per_symbol_cap))
    open_cap = int(cfg.get("max_open_positions") or 0)
    if open_cap and len(open_positions) + ctx["orders_in_batch"] >= open_cap:
        reasons.append("open positions %d + batch %d >= max_open_positions %d"
                       % (len(open_positions), ctx["orders_in_batch"], open_cap))
    sent_today = [r for r in ctx["sent_today"] if r.get("fingerprint") == fingerprint(order)]
    if sent_today:
        reasons.append("had l'order tsift lyoum deja / this exact order was already sent today")

    # margin
    try:
        need = b.margin(sym, volume, side, price)
        free = float(acct.get("margin_free") or 0.0)
        checks["margin"] = round(need, 2)
        checks["margin_free"] = round(free, 2)
        if need < 0:
            reasons.append("l'broker ma 9derch y7seb margin / broker cannot compute margin")
        elif need > free:
            reasons.append("margin %.2f > free margin %.2f / ma kaynch flous kafyin" % (need, free))
        elif free > 0 and need > 0:
            level_after = ((float(acct.get("margin") or 0) + need) and
                           (equity / (float(acct.get("margin") or 0) + need) * 100.0))
            floor = float(cfg.get("min_margin_level_pct") or 0)
            checks["margin_level_after"] = round(level_after or 0, 1)
            if floor and level_after and level_after < floor:
                reasons.append("margin level ba3d l'fill %.0f%% < floor %.0f%%"
                               % (level_after, floor))
    except BridgeError as e:
        reasons.append("margin check: %s" % e)

    # news blackout
    cal = ctx["calendar"]
    if cal:
        curs = {str(spec.get("currency_base") or "").upper(),
                str(spec.get("currency_profit") or "").upper()}
        curs.discard("")
        now = bridge_mod.now_utc()
        for window in cal.get("blackouts") or []:
            try:
                start = datetime.datetime.fromisoformat(window["from"])
                end = datetime.datetime.fromisoformat(window["to"])
            except (KeyError, ValueError):
                continue
            if start <= now <= end and (not window.get("currency") or window["currency"] in curs):
                reasons.append("news blackout: %s (%s) %s-%s"
                               % (window.get("title"), window.get("currency"),
                                  start.strftime("%H:%M"), end.strftime("%H:%M")))
                break

    # blocked hours (UTC)
    hour = bridge_mod.now_utc().hour
    if hour in [int(h) for h in (cfg.get("blocked_hours_utc") or [])]:
        reasons.append("hour %02d:00 UTC blocked f config / blocked trading hour" % hour)

    verdict = "PASS" if not reasons else "BLOCK"
    return verdict, reasons, checks


# ---------------------------------------------------------------- main

def load_orders(path):
    data = bridge_mod.read_json(path, None)
    if data is None:
        raise RiskError("no orders at %s - run mt5-budget first" % path)
    rows = data.get("orders", data) if isinstance(data, dict) else data
    if not rows:
        raise RiskError("orders.json khawi / no proposed orders")
    return [o for o in rows if isinstance(o, dict)]


def trades_today_from_deals(deals):
    today = utc_today()
    out = []
    for deal in deals or []:
        if parse_day(deal.get("time")) != today:
            continue
        entry = deal.get("entry")
        if entry not in (1, "1", "DEAL_ENTRY_OUT"):   # 1 = out (a closing deal)
            continue
        out.append(deal)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pre-trade risk gate: PASS or BLOCK every order.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--orders", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    cfg = b.cfg
    try:
        orders = load_orders(a.orders or os.path.join(a.trader_dir, "orders.json"))
        positions = b.positions()
        deals = []
        try:
            deals = b.deals()
        except BridgeError:
            deals = []
        trades_today = trades_today_from_deals(deals)
        state = bridge_mod.read_json(os.path.join(a.trader_dir, "state", "broker.json"), {}) or {}
        if "decisions" not in state and isinstance(state, list):  # old flat format
            state = {"decisions": state}
        calendar = bridge_mod.read_json(os.path.join(a.trader_dir, "calendar.json"), {}) or {}

        blocks, summary = global_blocks(b, cfg, orders, state, trades_today)
        ctx = {
            "account": b.account(),
            "positions": positions,
            "calendar": calendar,
            "lots_in_batch": 0.0,
            "symbol_in_batch": {},
            "orders_in_batch": 0,
            "sent_today": [d for d in (state.get("decisions") or [])
                           if d.get("date") == utc_today() and d.get("action") == "sent"],
        }

        results = []
        for order in orders:
            fp = fingerprint(order)
            if blocks:
                verdict, reasons, checks = "BLOCK", list(blocks), {}
            else:
                verdict, reasons, checks = check_order(b, cfg, order, ctx)
            results.append({
                "order_id": order.get("id"), "fingerprint": fp, "verdict": verdict,
                "reasons": reasons, "checks": checks, "order": order,
            })
            if verdict == "PASS":
                # a PASS behaves as if it filled, so the next order is checked
                # against the world that would exist after it
                ctx["lots_in_batch"] += float(order.get("volume") or 0)
                ctx["orders_in_batch"] += 1
                sym = str(order.get("symbol", "")).upper()
                ctx["symbol_in_batch"][sym] = ctx["symbol_in_batch"].get(sym, 0) + 1

        passed = [r for r in results if r["verdict"] == "PASS"]
        payload = {
            "generated": bridge_mod.now_utc().isoformat(),
            "date": utc_today(), "mode": b.mode,
            "account": {"login": ctx["account"].get("login"),
                        "server": ctx["account"].get("server"),
                        "is_real": ctx["account"].get("is_real"),
                        "equity": ctx["account"].get("equity"),
                        "currency": ctx["account"].get("currency")},
            "global_blocks": blocks, "summary": summary,
            "counts": {"total": len(results), "pass": len(passed),
                       "block": len(results) - len(passed)},
            "results": results,
        }
        if not a.no_write:
            path = os.path.join(a.trader_dir, "state", "risk.json")
            bridge_mod.write_json(path, payload)
            payload["written_to"] = path

        if a.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            for block in blocks:
                print("ALL BLOCKED: %s" % block)
            for row in results:
                order = row["order"]
                print("%-5s %-8s %-4s %-6s lots=%-6s risk=%s%%  %s"
                      % (row["verdict"], order.get("symbol"), order.get("side"),
                         order.get("type", "market"), order.get("volume"),
                         row["checks"].get("risk_pct", "?"),
                         "" if row["verdict"] == "PASS" else "| " + "; ".join(row["reasons"])))
            print("\n%d pass, %d block" % (payload["counts"]["pass"], payload["counts"]["block"]))
        return 0 if payload["counts"]["block"] == 0 else 1
    except (RiskError, BridgeError) as e:
        print("RISK ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
