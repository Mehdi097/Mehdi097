#!/usr/bin/env python3
"""rebalance.py - what you are actually exposed to, and how far it drifted.

Per symbol you get the signed lots, the money each point of movement is worth
with that net position, and the share of the portfolio. Across symbols you get
the currency tilt (long EUR, short USD, ...) and the total money-per-point the
book carries. If trader/targets.json exists, you also get the drift against
your target weights and the trades that would close it.

    python3 rebalance.py                          # exposure table + drift
    python3 rebalance.py --band 5                 # only report drift over 5 points
    python3 rebalance.py --write-orders --band 5  # propose orders -> trader/orders.json
    python3 rebalance.py --json
    python3 rebalance.py --offline

Proposals go through mt5-risk and mt5-broker like everything else: this file
never sends an order.
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


def notional_account(b, symbol, lots, price):
    """Rough value of a position in the account currency, with an honest flag."""
    ccy = b.cfg.get("account_currency") or b.account().get("currency") or "USD"
    spec = b.spec(symbol)
    contract = float(spec.get("contract_size") or 0)
    if contract <= 0 or not price:
        return 0.0, "unknown"
    if (spec.get("currency_profit") or "").upper() == ccy.upper():
        return lots * contract * price, "exact"
    if (spec.get("currency_base") or "").upper() == ccy.upper():
        return lots * contract, "exact"
    return lots * contract * price, "approximate"


def build_exposure(b, positions):
    rows = {}
    for pos in positions:
        sym = pos["symbol"]
        sign = 1.0 if pos["side"] == "buy" else -1.0
        row = rows.setdefault(sym, {"symbol": sym, "lots": 0.0, "positions": 0,
                                    "floating": 0.0, "buy_lots": 0.0, "sell_lots": 0.0})
        row["lots"] += sign * float(pos["volume"])
        row["buy_lots"] += float(pos["volume"]) if sign > 0 else 0.0
        row["sell_lots"] += float(pos["volume"]) if sign < 0 else 0.0
        row["positions"] += 1
        row["floating"] += float(pos.get("profit") or 0)
    out = {}
    total_abs = 0.0
    for sym, row in rows.items():
        try:
            spec = b.spec(sym)
            tick = b.tick(sym)
        except BridgeError:
            out[sym] = row
            continue
        price = float(tick.get("mid") or tick.get("bid") or 0)
        vpp = sizing.value_per_point(spec)
        notional, quality = notional_account(b, sym, abs(row["lots"]), price)
        row.update({
            "price": round(price, int(spec.get("digits", 5))),
            "value_per_point_per_lot": round(vpp, 6),
            "money_per_point": round(row["lots"] * vpp, 4),
            "notional": round(notional, 2), "notional_quality": quality,
            "hedged": bool(row["buy_lots"] and row["sell_lots"]),
            "floating": round(row["floating"], 2),
        })
        total_abs += notional
        out[sym] = row
    for row in out.values():
        if total_abs > 0 and row.get("notional") is not None:
            row["share_pct"] = round(row["notional"] / total_abs * 100.0, 2)
    return out, total_abs


def currency_tilt(b, exposure, total_abs):
    """Signed exposure per currency, in % of the book. FX only, by design."""
    tilt = {}
    for sym, row in exposure.items():
        try:
            spec = b.spec(sym)
        except BridgeError:
            continue
        base = (spec.get("currency_base") or "").upper()
        quote = (spec.get("currency_profit") or "").upper()
        if not base or not quote or len(base) != 3 or len(quote) != 3:
            continue
        lots = float(row.get("lots") or 0)
        contract = float(spec.get("contract_size") or 0)
        price = float(row.get("price") or 0)
        tilt[base] = tilt.get(base, 0.0) + lots * contract
        tilt[quote] = tilt.get(quote, 0.0) - lots * contract * price
    peak = max([abs(v) for v in tilt.values()] or [1.0]) or 1.0
    return {cur: {"units": round(value, 2), "tilt_pct": round(value / peak * 100.0, 1)}
            for cur, value in sorted(tilt.items(), key=lambda kv: -abs(kv[1]))}


def drift(b, exposure, total_abs, targets_path):
    data = bridge_mod.read_json(targets_path, None)
    if not data:
        return None
    rows = data.get("targets", data) if isinstance(data, dict) else data
    targets = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("symbol"):
            targets[str(row["symbol"]).upper()] = {
                "weight": float(row.get("weight") or 0),
                "side": str(row.get("side") or "buy").lower(),
                "stop_pips": row.get("stop_pips"), "tp_pips": row.get("tp_pips"),
            }
    out = []
    for sym in sorted(set(list(targets) + list(exposure))):
        row = exposure.get(sym) or {}
        actual_weight = float(row.get("share_pct") or 0.0)
        target = targets.get(sym)
        target_weight = float(target["weight"]) if target else 0.0
        out.append({
            "symbol": sym, "target_weight": round(target_weight, 2),
            "actual_weight": round(actual_weight, 2),
            "drift": round(actual_weight - target_weight, 2),
            "actual_lots": round(float(row.get("lots") or 0), 4),
            "target_side": (target or {}).get("side", "buy"),
            "stop_pips": (target or {}).get("stop_pips"),
            "tp_pips": (target or {}).get("tp_pips"),
            "notional": row.get("notional"),
        })
    out.sort(key=lambda r: -abs(r["drift"]))
    return out


def propose_orders(b, drift_rows, band, equity):
    orders = []
    for row in drift_rows:
        if abs(row["drift"]) < band:
            continue
        sym = row["symbol"]
        try:
            spec = b.spec(sym)
            tick = b.tick(sym)
        except BridgeError:
            continue
        price = float(tick.get("ask") or 0)
        contract = float(spec.get("contract_size") or 0)
        if price <= 0 or contract <= 0:
            continue
        # how much notional to add/remove to close the weight gap
        gap_pct = -row["drift"]                     # negative drift = under target
        if gap_pct > 0:
            side = "buy"
        elif gap_pct < 0:
            side = "sell"
        else:
            continue
        base_notional = abs(float(row.get("notional") or 0)) or 1.0
        delta_volume = abs(gap_pct) / 100.0 * base_notional / (contract * price)
        volume, clamped = sizing.normalise_volume(spec, delta_volume, "down")
        if volume <= 0:
            continue
        if side == "sell":
            # never propose selling more than you hold unless it is a reversal
            held = max(0.0, float(row.get("actual_lots") or 0))
            volume = min(volume, held) if held else 0.0
            if volume <= 0:
                continue
        stop_pips = row.get("stop_pips") or b.cfg.get("default_stop_pips", 20)
        pip = sizing.pip_size(spec)
        sl = sizing.round_price(spec, price - float(stop_pips) * pip if side == "buy"
                                else price + float(stop_pips) * pip)
        tp_pips = row.get("tp_pips") or round(float(stop_pips) * float(b.cfg.get("min_reward_risk", 1.5)), 1)
        tp = sizing.round_price(spec, price + float(tp_pips) * pip if side == "buy"
                                else price - float(tp_pips) * pip)
        risk_money = None
        try:
            risk_money = round(sizing.loss_per_lot(spec, abs(price - sl)) * volume, 2)
        except sizing.SizingError:
            pass
        orders.append({
            "id": "%s-%s-%s" % (sym, side, datetime.datetime.now().strftime("%Y%m%d%H%M%S")),
            "symbol": sym, "side": side, "type": "market", "volume": volume,
            "price": None, "entry_ref": round(price, int(spec.get("digits", 5))),
            "sl": sl, "tp": tp, "stop_pips": round(float(stop_pips), 2),
            "tp_pips": round(float(tp_pips), 2),
            "reward_risk": sizing.reward_risk(price, sl, tp),
            "risk_pct": round(risk_money / equity * 100.0, 3) if risk_money and equity else None,
            "risk_money": risk_money,
            "weight": round(abs(row["target_weight"]), 2),
            "magic": int(b.cfg.get("magic", 20261106)),
            "deviation": int(b.cfg.get("deviation", 20)),
            "comment": "mt5-rebalance %+.1fpp" % row["drift"],
            "reason": "drift %+.2f points (target %.2f%%, actual %.2f%%)"
                      % (row["drift"], row["target_weight"], row["actual_weight"]),
            "notes": [], "spread_points": tick.get("spread_points"), "pip": pip,
        })
    return orders


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exposure, currency tilt and drift rebalancing.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--targets", default=None)
    ap.add_argument("--band", type=float, default=5.0)
    ap.add_argument("--write-orders", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    try:
        positions = b.positions()
        exposure, total_abs = build_exposure(b, positions)
        tilt = currency_tilt(b, exposure, total_abs)
        targets_path = a.targets or os.path.join(a.trader_dir, "targets.json")
        drift_rows = drift(b, exposure, total_abs, targets_path)
        acct = b.account()
        equity = float(acct.get("equity") or 0.0)
        orders = propose_orders(b, drift_rows, a.band, equity) if drift_rows else []

        payload = {
            "generated": bridge_mod.now_utc().isoformat(), "mode": b.mode,
            "equity": equity, "currency": acct.get("currency"),
            "positions": len(positions),
            "total_notional": round(total_abs, 2),
            "total_money_per_point": round(sum(r.get("money_per_point") or 0
                                               for r in exposure.values()), 4),
            "floating": round(sum(float(p.get("profit") or 0) for p in positions), 2),
            "exposure": exposure, "currency_tilt": tilt,
            "drift": drift_rows, "band": a.band,
            "proposed_orders": orders,
        }
        if a.write_orders and orders:
            path = os.path.join(a.trader_dir, "orders.json")
            bridge_mod.write_json(path, {
                "generated": payload["generated"], "mode": b.mode, "source": "rebalance",
                "equity": equity, "currency": acct.get("currency"),
                "orders": orders, "skipped": [],
            })
            payload["written_to"] = path

        if a.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return 0

        print("%d positions, %.2f %s total notional, %.2f per point, floating %.2f"
              % (payload["positions"], payload["total_notional"], payload["currency"],
                 payload["total_money_per_point"], payload["floating"]))
        for sym, row in sorted(exposure.items(), key=lambda kv: -abs(kv[1]["lots"])):
            print("  %-8s %+7.2f lots  %5s%%  %+9.2f per point  floating %+8.2f%s"
                  % (sym, row["lots"], row.get("share_pct", "?"), row.get("money_per_point") or 0,
                     row.get("floating") or 0, "  (hedged)" if row.get("hedged") else ""))
        if tilt:
            print("currency tilt:", ", ".join("%s %+.0f%%" % (c, v["tilt_pct"])
                                              for c, v in list(tilt.items())[:6]))
        if drift_rows:
            print("\ndrift (band %.1f points):" % a.band)
            for row in drift_rows:
                flag = "REBALANCE" if abs(row["drift"]) >= a.band else "ok"
                print("  %-8s target %5.1f%%  actual %5.1f%%  drift %+6.2f  %s"
                      % (row["symbol"], row["target_weight"], row["actual_weight"],
                         row["drift"], flag))
        else:
            print("\nma kaynch targets / no targets.json - nothing to rebalance against")
        if orders:
            print("\n%d proposed orders%s:" % (len(orders),
                                               " -> trader/orders.json" if a.write_orders else " (dry run)"))
            for o in orders:
                print("  %-8s %-4s %.2f lots  SL %s  %s" % (o["symbol"], o["side"], o["volume"],
                                                            o["sl"], o["reason"]))
            print("daba: mt5-risk check.py -> mt5-broker execute.py show")
        return 0
    except BridgeError as e:
        print("EXPOSURE ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
