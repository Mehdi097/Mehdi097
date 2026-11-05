#!/usr/bin/env python3
"""size.py - turn target weights into real lot sizes and exact SL/TP prices.

This is the step that decides how much money each idea gets. It reads
trader/targets.json (from mt5-screener or mt5-copycat), the account equity from
MT5, and each symbol's own contract spec, then writes trader/orders.json as
proposals. Nothing is sent here.

    python3 size.py                              # show the plan, write nothing
    python3 size.py --write                      # -> trader/orders.json
    python3 size.py --risk 0.25 --write          # override the per-trade risk %
    python3 size.py --equity 5000 --offline      # plan against a number, no terminal
    python3 size.py --fixed-lot 0.1 --write      # ignore risk sizing, same lots everywhere

How the money is split:

  1. risk budget     portfolio_risk_pct is the most all open trades may lose
                     together. Each idea gets risk budget x its weight.
  2. per-trade cap   no single trade may risk more than max_risk_pct_per_trade,
                     whatever its weight says.
  3. stop first      the SL distance (from the target, or ATR x multiple) comes
                     first; the lot is whatever loses exactly that risk at that
                     stop. Wider stop -> smaller lot, same money.
  4. broker minimum  if even the minimum lot risks more than the cap, the trade
                     is SKIPPED, not rounded up. --allow-min-lot overrides, with
                     a warning that the risk is higher than you asked.
  5. lots ceiling    max_lots_per_order, then max_total_lots across the batch.
  6. margin          if the batch needs more free margin than you have (keeping
                     min_margin_level_pct), the last ideas are dropped, not sent.
"""

import argparse
import datetime
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


class SizeError(Exception):
    pass


def read_targets(path):
    data = bridge_mod.read_json(path, None)
    if data is None:
        raise SizeError("no targets at %s - run mt5-screener or mt5-copycat first" % path)
    rows = data.get("targets", data) if isinstance(data, dict) else data
    if not rows:
        raise SizeError("targets.json khawi / targets empty")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        out.append({
            "symbol": str(row["symbol"]).upper(),
            "side": str(row.get("side") or "buy").lower(),
            "weight": row.get("weight"),
            "stop_pips": row.get("stop_pips", row.get("sl_pips")),
            "tp_pips": row.get("tp_pips"),
            "volume": row.get("volume"),
            "reason": row.get("reason", ""),
        })
    if not out:
        raise SizeError("ma kaynch target s7i7 / no valid target rows")
    weights = [t["weight"] for t in out if isinstance(t["weight"], (int, float))]
    for t in out:
        if not isinstance(t["weight"], (int, float)):
            t["weight"] = round(100.0 / len(out), 4)
    total = sum(float(t["weight"]) for t in out)
    if total <= 0:
        raise SizeError("weights koulhom 0 / all weights are zero")
    for t in out:
        t["weight"] = round(float(t["weight"]) / total * 100.0, 4)
    return out


def plan_order(b, target, cfg, equity, risk_override=None, fixed_lot=None):
    """One target -> one proposed order, or a skip with the reason."""
    sym = target["symbol"]
    side = target["side"]
    if side not in ("buy", "sell"):
        raise SizeError("%s: side khass buy wla sell, machi %r" % (sym, side))
    spec = b.spec(sym)
    tick = b.tick(sym)
    digits = int(spec.get("digits", 5))
    pip = sizing.pip_size(spec)
    entry = float(tick["ask"] if side == "buy" else tick["bid"])
    if entry <= 0:
        return None, "%s: no quote (bid/ask = 0). Market closed?" % sym

    stop_pips = target.get("stop_pips")
    if stop_pips in (None, 0, 0.0):
        stop_pips = cfg.get("default_stop_pips", 20)
    stop_pips = float(stop_pips)
    tp_pips = target.get("tp_pips")
    if tp_pips in (None, 0, 0.0):
        tp_pips = round(stop_pips * float(cfg.get("min_reward_risk", 1.5)), 1)
    tp_pips = float(tp_pips)

    sl = sizing.round_price(spec, entry - stop_pips * pip if side == "buy" else entry + stop_pips * pip)
    tp = sizing.round_price(spec, entry + tp_pips * pip if side == "buy" else entry - tp_pips * pip)
    ok, issues, sl_dist, tp_dist = sizing.stops_ok(spec, side, entry, sl, tp,
                                                    tick.get("spread_points") or 0)
    notes = []
    if not ok:
        # widen to the broker's minimum distance instead of sending an invalid stop
        min_points = int(spec.get("stops_level_points") or 0) + int(tick.get("spread_points") or 0)
        if min_points and (sl_dist < min_points * sizing.point_size(spec)):
            stop_pips = max(stop_pips, (min_points + 5) * sizing.point_size(spec) / pip)
            sl = sizing.round_price(spec, entry - stop_pips * pip if side == "buy" else entry + stop_pips * pip)
            notes.append("SL widened to broker minimum (%.1f pips)" % stop_pips)
            ok, issues, sl_dist, tp_dist = sizing.stops_ok(spec, side, entry, sl, tp,
                                                            tick.get("spread_points") or 0)
        if not ok:
            return None, "%s: stop invalid - %s" % (sym, "; ".join(issues))

    risk_pct = risk_override if risk_override is not None else (
        float(cfg.get("portfolio_risk_pct", 3.0)) * float(target["weight"]) / 100.0)
    cap = float(cfg.get("max_risk_pct_per_trade", 1.0))
    if risk_pct > cap:
        notes.append("risk %.2f%% capped at %.2f%%" % (risk_pct, cap))
        risk_pct = cap
    if risk_pct <= 0:
        return None, "%s: risk 0%% - nothing to size" % sym

    if fixed_lot:
        volume, meta = sizing.normalise_volume(spec, float(fixed_lot), "down")
        meta = {"volume": volume, "risk_pct": None, "risk_money": None, "actual_risk": None,
                "actual_risk_pct": None, "skipped": volume <= 0, "reasons": ["fixed_lot"],
                "sl_pips": round(stop_pips, 2), "clamped": None,
                "loss_per_lot": round(sizing.loss_per_lot(spec, sl_dist), 2)}
        if volume <= 0:
            return None, "%s: fixed lot below volume_min" % sym
    else:
        volume, meta = sizing.volume_for_risk(
            equity, risk_pct, sl_dist, spec,
            allow_min_lot=bool(cfg.get("allow_min_lot", False)),
            max_volume=float(cfg.get("max_lots_per_order") or 1e9))
        if meta.get("skipped"):
            return None, "%s: %s" % (sym, " ".join(meta.get("reasons") or ["volume 0"]))
    notes.extend(meta.get("reasons") or [])

    order = {
        "id": "%s-%s-%s" % (sym, side, datetime.datetime.now().strftime("%Y%m%d%H%M%S")),
        "symbol": sym, "side": side, "type": "market",
        "volume": volume, "price": None,
        "entry_ref": round(entry, digits), "sl": sl, "tp": tp,
        "stop_pips": round(stop_pips, 2), "tp_pips": round(tp_pips, 2),
        "reward_risk": sizing.reward_risk(entry, sl, tp),
        "risk_pct": round(risk_pct, 3),
        "risk_money": meta.get("actual_risk"),
        "weight": target["weight"],
        "magic": int(cfg.get("magic", 20261106)),
        "deviation": int(cfg.get("deviation", 20)),
        "comment": ("mt5-budget %.1f%%" % risk_pct)[:31],
        "reason": target.get("reason", ""),
        "notes": notes,
        "spread_points": tick.get("spread_points"),
        "pip": pip,
    }
    return order, None


def load_equity(b, override):
    if override:
        return float(override), "override"
    acct = b.account()
    if acct.get("currency") and b.cfg.get("account_currency") and \
            acct["currency"] != b.cfg["account_currency"]:
        print("warning: account currency %s != config %s - sizes assume the account currency"
              % (acct["currency"], b.cfg["account_currency"]), file=sys.stderr)
    return float(acct.get("equity") or acct.get("balance") or 0.0), "account"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Size targets into lots with SL/TP from symbol specs.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--targets", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--risk", type=float, default=None, help="per-trade risk %% (overrides weights)")
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--fixed-lot", type=float, default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    cfg = b.cfg
    try:
        targets = read_targets(a.targets or os.path.join(a.trader_dir, "targets.json"))
        equity, equity_src = load_equity(b, a.equity)
        if equity <= 0:
            raise SizeError("equity = 0: account ma 3ndoch flous / no equity to size")

        orders, skips = [], []
        for target in targets:
            try:
                order, why = plan_order(b, target, cfg, equity, a.risk, a.fixed_lot)
            except BridgeError as e:
                order, why = None, "%s: %s" % (target["symbol"], e)
            if order:
                orders.append(order)
            else:
                skips.append({"symbol": target["symbol"], "reason": why})

        # total lots ceiling: scale everything down proportionally, never up
        max_total = float(cfg.get("max_total_lots") or 0)
        total_lots = sum(o["volume"] for o in orders)
        scaled = False
        if max_total and total_lots > max_total + 1e-9:
            factor = max_total / total_lots
            for o in orders:
                spec = b.spec(o["symbol"])
                o["volume"], _ = sizing.normalise_volume(spec, o["volume"] * factor, "down")
                o["notes"].append("scaled to max_total_lots")
            orders = [o for o in orders if o["volume"] > 0]
            scaled = True

        # margin ceiling: drop from the end until the batch fits
        acct = b.account()
        free = float(acct.get("margin_free") or 0.0)
        level = float(cfg.get("min_margin_level_pct") or 300)
        reserve = free - (free * min(level, 100) / 100.0) if level < 100 else 0.0
        usable = max(0.0, free - reserve)
        margin_needed = 0.0
        kept = []
        for order in orders:
            try:
                need = b.margin(order["symbol"], order["volume"], order["side"], order["entry_ref"])
            except BridgeError:
                need = -1
            if need < 0:
                order["notes"].append("margin unknown (broker says -1); kept")
                kept.append(order)
                continue
            if margin_needed + need > usable and usable > 0:
                skips.append({"symbol": order["symbol"],
                              "reason": "margin: needs %.2f, only %.2f usable free margin"
                                        % (need, usable - margin_needed)})
                continue
            margin_needed += need
            order["margin"] = round(need, 2)
            kept.append(order)
        orders = kept

        payload = {
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": b.mode, "equity": round(equity, 2), "equity_source": equity_src,
            "currency": acct.get("currency"),
            "risk_budget_pct": round(sum(o["risk_pct"] for o in orders), 3),
            "risk_budget_money": round(sum(o["risk_money"] or 0 for o in orders), 2),
            "total_lots": round(sum(o["volume"] for o in orders), 4),
            "margin_used": round(sum(o.get("margin") or 0 for o in orders), 2),
            "scaled_to_max_total_lots": scaled,
            "orders": orders, "skipped": skips,
        }
        if a.write:
            path = os.path.join(a.trader_dir, "orders.json")
            bridge_mod.write_json(path, payload)
            print("orders -> %s (%d orders, %.2f lots, risk %.2f%% = %.2f %s)"
                  % (path, len(orders), payload["total_lots"], payload["risk_budget_pct"],
                     payload["risk_budget_money"], payload["currency"]))
            for s in skips:
                print("SKIP %-8s %s" % (s["symbol"], s["reason"]), file=sys.stderr)
        if a.json or not a.write:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            for o in orders:
                print("%-8s %-4s %.2f lots  SL %s (%s pips)  TP %s  risk %.2f%% (%.2f)  RR %s"
                      % (o["symbol"], o["side"], o["volume"], o["sl"], o["stop_pips"],
                         o["tp"], o["risk_pct"], o["risk_money"] or 0, o["reward_risk"]))
        return 0
    except (SizeError, BridgeError) as e:
        print("BUDGET ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
