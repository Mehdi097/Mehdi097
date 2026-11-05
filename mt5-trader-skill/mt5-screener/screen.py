#!/usr/bin/env python3
"""screen.py - filter your universe against your own rules and rank what passes.

Reads trader/metrics.json (from mt5-analyst) and trader/rules.json, then marks
every symbol PASS or FAIL with the reason, and ranks the survivors. With
--write-targets it also writes trader/targets.json, which mt5-budget sizes.

    python3 screen.py                                  # trader/metrics.json + trader/rules.json
    python3 screen.py --rules rules.json --json
    python3 screen.py --trend up --top 4 --write-targets
    python3 screen.py --show-fails

rules.json (see rules.example.json):

    {"min_atr_pips": 8, "max_spread_points": 25, "max_spread_to_atr": 0.12,
     "min_adr_pips": 40, "trend": "any", "min_reward_risk": 1.5,
     "max_swap_per_lot": 40, "rank_by": "trend_strength", "top": 5,
     "blocked_symbols": [], "sides": "trend"}

Nothing here talks to a broker. It only chooses ideas; mt5-budget puts money on
them, mt5-risk can still block every one of them.
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

DEFAULT_RULES = {
    "min_atr_pips": 0,
    "max_spread_points": 100,
    "max_spread_to_atr": 0.30,
    "min_adr_pips": 0,
    "trend": "any",                 # up | down | flat | any
    "timeframe": "D1",              # which trend column to obey
    "min_reward_risk": 1.0,
    "max_swap_per_lot": None,
    "rank_by": "trend_strength",    # trend_strength | volatility | cost
    "top": 5,
    "blocked_symbols": [],
    "sides": "trend",               # trend | buy | sell | both
    "stop_atr_multiple": 1.5,
}


class ScreenError(Exception):
    pass


def load_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise ScreenError("no %s at %s" % (what, path))
        return None
    return bridge_mod.read_json(path)


def check_symbol(row, rules):
    """Every reason this symbol fails, plus the score components."""
    fails, notes = [], []
    sym = row.get("symbol")
    if row.get("error"):
        return ["data error: %s" % row["error"]], [], None, {}, (None, None)
    atr = row.get("atr_h1_pips") or 0
    adr_pips = row.get("adr20_pips") or 0
    spread = row.get("spread_points")
    avg_spread = row.get("avg_spread_points") or spread or 0
    trend = row.get(("trend_%s" % rules.get("timeframe", "D1")).lower(),
                    row.get("trend_d1"))
    rr = row.get("suggested_stop_pips"), row.get("suggested_tp_pips")

    if sym in (rules.get("blocked_symbols") or []):
        fails.append("blocked symbol")
    if atr < float(rules.get("min_atr_pips") or 0):
        fails.append("ATR %.1f pips < min %.1f" % (atr, float(rules.get("min_atr_pips"))))
    if adr_pips and adr_pips < float(rules.get("min_adr_pips") or 0):
        fails.append("ADR %.1f pips < min %.1f" % (adr_pips, float(rules.get("min_adr_pips"))))
    if spread is not None and spread > float(rules.get("max_spread_points") or 10 ** 6):
        fails.append("spread %s points > max %s" % (spread, rules.get("max_spread_points")))
    if spread and atr:
        ratio = float(spread) / (atr * 10.0)      # points vs pips
        if ratio > float(rules.get("max_spread_to_atr") or 1.0):
            fails.append("spread is %.0f%% of ATR (max %.0f%%)"
                         % (ratio * 100, float(rules.get("max_spread_to_atr")) * 100))
    wanted = str(rules.get("trend", "any")).lower()
    if wanted != "any" and trend != wanted:
        fails.append("trend %s, wanted %s" % (trend, wanted))
    if trend == "unknown":
        notes.append("trend unknown (not enough daily bars)")
    if rr[0] and rr[1]:
        value = float(rr[1]) / float(rr[0]) if float(rr[0]) else 0
        if rr[0] and value + 1e-9 < float(rules.get("min_reward_risk") or 0):
            fails.append("reward:risk %.2f < min %.2f" % (value, float(rules.get("min_reward_risk"))))
    swap_cap = rules.get("max_swap_per_lot")
    if swap_cap is not None:
        worst = max(abs(row.get("swap_long") or 0), abs(row.get("swap_short") or 0))
        if worst > float(swap_cap):
            fails.append("swap %.2f > max %.2f" % (worst, float(swap_cap)))

    sides = str(rules.get("sides", "trend")).lower()
    if sides in ("buy", "sell"):
        side = sides
    elif sides == "both":
        side = "sell" if trend == "down" else "buy"
    elif trend == "up":
        side = "buy"
    elif trend == "down":
        side = "sell"
    else:
        side = None
        notes.append("no side: trend is %s" % trend)

    score = {
        "trend_strength": abs(float(row.get("ema_slope_d1_pct") or 0)),
        "volatility": float(atr),
        "cost": -float(spread or 0),
        "spread_vs_atr": (float(spread or 0) / (atr * 10.0)) if atr else 99.0,
    }
    return fails, notes, (side if not fails else None), score, rr


def main(argv=None):
    ap = argparse.ArgumentParser(description="Screen symbols against your rules and rank the passers.")
    ap.add_argument("metrics", nargs="?", default=None)
    ap.add_argument("--rules", default=None)
    ap.add_argument("--trader-dir", default=None)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--trend", default=None, choices=["up", "down", "flat", "any"])
    ap.add_argument("--rank-by", default=None,
                    choices=["trend_strength", "volatility", "cost", "spread_vs_atr"])
    ap.add_argument("--show-fails", action="store_true")
    ap.add_argument("--write-targets", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    metrics_path = a.metrics
    if not metrics_path:
        metrics_path = os.path.join(a.trader_dir or "trader", "metrics.json")
    trader_dir = a.trader_dir or os.path.dirname(os.path.abspath(metrics_path)) or "trader"
    rules_path = a.rules or os.path.join(trader_dir, "rules.json")
    rules = dict(DEFAULT_RULES)
    loaded = load_json(rules_path, "rules", required=False)
    if loaded:
        rules.update(loaded)
    if a.trend:
        rules["trend"] = a.trend
    if a.rank_by:
        rules["rank_by"] = a.rank_by
    top = a.top if a.top is not None else int(rules.get("top") or 5)

    data = load_json(metrics_path, "metrics")
    rows = data.get("symbols", data) if isinstance(data, dict) else {}
    if not rows:
        raise SystemExit("metrics khawya / metrics empty: run mt5-analyst first")

    passed, failed = [], []
    for sym in sorted(rows):
        row = dict(rows[sym])
        row.setdefault("symbol", sym)
        fails, notes, side, score, rr = check_symbol(row, rules)
        entry = {
            "symbol": sym, "side": side,
            "fails": fails, "notes": notes,
            "atr_h1_pips": row.get("atr_h1_pips"), "adr20_pips": row.get("adr20_pips"),
            "spread_points": row.get("spread_points"),
            "trend_d1": row.get("trend_d1"), "trend_h1": row.get("trend_h1"),
            "rsi_h1": row.get("rsi_h1"),
            "suggested_stop_pips": row.get("suggested_stop_pips"),
            "suggested_tp_pips": row.get("suggested_tp_pips"),
            "score": score, "price": row.get("price"),
        }
        (passed if (not fails and side) else failed).append(entry)

    key = rules.get("rank_by", "trend_strength")
    if key == "cost":
        passed.sort(key=lambda e: e["score"]["cost"], reverse=True)
    elif key == "spread_vs_atr":
        passed.sort(key=lambda e: e["score"]["spread_vs_atr"])
    else:
        passed.sort(key=lambda e: e["score"].get(key, 0), reverse=True)
    passed = passed[:top]

    weight_mode = str(rules.get("weights", "equal")).lower()
    raw = []
    for e in passed:
        if weight_mode == "volatility":
            raw.append(max(0.1, e["score"].get("volatility", 1.0)))
        elif weight_mode == "trend_strength":
            raw.append(max(0.1, e["score"].get("trend_strength", 1.0)))
        else:
            raw.append(1.0)
    total = sum(raw) or 1.0
    for e, w in zip(passed, raw):
        e["weight"] = round(w / total * 100.0, 2)

    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rules": rules, "passed": passed,
        "failed": failed if a.show_fails else [
            {"symbol": e["symbol"], "fails": e["fails"]} for e in failed],
        "counts": {"passed": len(passed), "failed": len(failed)},
    }

    if a.write_targets:
        targets = {
            "source": "screener",
            "generated": payload["generated"],
            "targets": [{
                "symbol": e["symbol"], "side": e["side"], "weight": e["weight"],
                "stop_pips": e["suggested_stop_pips"], "tp_pips": e["suggested_tp_pips"],
                "reason": "screener: %s trend, ATR %s pips, spread %s"
                          % (e["trend_d1"], e["atr_h1_pips"], e["spread_points"]),
            } for e in passed],
        }
        path = os.path.join(trader_dir, "targets.json")
        bridge_mod.write_json(path, targets)
        print("targets -> %s (%d symbols)" % (path, len(targets["targets"])))

    if a.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        for e in passed:
            print("PASS %-8s %-4s weight %5.1f%%  ATR %s pips  spread %s"
                  % (e["symbol"], e["side"], e["weight"], e["atr_h1_pips"], e["spread_points"]))
        for e in failed:
            print("FAIL %-8s %s" % (e["symbol"], "; ".join(e["fails"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
