#!/usr/bin/env python3
"""journal.py - what your trading actually did, from MT5's own deal history.

MetaTrader keeps every deal. This turns them into closed trades (one row per
position), then into the numbers that decide whether a system is worth keeping:
net, win rate, profit factor, expectancy, average win and loss, streaks, the
drawdown of the equity curve, and the breakdown by symbol, hour, weekday and
magic number.

    python3 journal.py --days 30                 # text report
    python3 journal.py --days 90 --json
    python3 journal.py --symbol EURUSD
    python3 journal.py --write                   # -> trader/state/journal.json
    python3 journal.py --offline                 # use the snapshot's deals

Deals with entry = IN are openings, entry = OUT close them. P&L is profit +
commission + swap, exactly what the terminal shows in the account history.
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
Bridge = bridge_mod.Bridge
BridgeError = bridge_mod.BridgeError

ENTRY_IN, ENTRY_OUT = 0, 1


def deal_time(deal):
    value = deal.get("time")
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
    parsed = bridge_mod.__dict__.get("parse_time")
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def net(deal):
    return (float(deal.get("profit") or 0.0) + float(deal.get("commission") or 0.0)
            + float(deal.get("swap") or 0.0))


def build_trades(deals):
    """One row per position_id: opened, closed, volume, net, duration."""
    groups = {}
    for deal in deals:
        pid = deal.get("position_id") or deal.get("position") or deal.get("ticket")
        groups.setdefault(pid, []).append(deal)
    trades = []
    for pid, rows in groups.items():
        rows.sort(key=lambda d: (deal_time(d) or datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc)))
        ins = [r for r in rows if int(r.get("entry", -1)) == ENTRY_IN]
        outs = [r for r in rows if int(r.get("entry", -1)) in (ENTRY_OUT, 3)]
        if not outs:
            continue                      # still open
        volume_in = sum(float(r.get("volume") or 0) for r in ins) or float(rows[0].get("volume") or 0)
        volume_out = sum(float(r.get("volume") or 0) for r in outs)
        if volume_out + 1e-9 < volume_in:
            continue                      # partially closed; not a finished trade yet
        opened = deal_time(ins[0]) if ins else deal_time(rows[0])
        closed = deal_time(outs[-1])
        price_in = (sum(float(r.get("price") or 0) * float(r.get("volume") or 0) for r in ins)
                    / volume_in) if ins and volume_in else float(rows[0].get("price") or 0)
        pnl = round(sum(net(r) for r in rows), 2)
        trades.append({
            "position_id": pid,
            "symbol": rows[0].get("symbol"),
            "side": "buy" if int(ins[0].get("type", 0)) == 0 else "sell" if ins else "unknown",
            "volume": round(volume_in, 4),
            "price_in": round(price_in, 6),
            "price_out": round(float(outs[-1].get("price") or 0), 6),
            "opened": opened.isoformat() if opened else None,
            "closed": closed.isoformat() if closed else None,
            "duration_min": round((closed - opened).total_seconds() / 60.0, 1)
            if opened and closed else None,
            "net": pnl,
            "commission": round(sum(float(r.get("commission") or 0) for r in rows), 2),
            "swap": round(sum(float(r.get("swap") or 0) for r in rows), 2),
            "magic": rows[0].get("magic"),
            "comment": rows[0].get("comment", ""),
            "hour": opened.hour if opened else None,
            "weekday": opened.strftime("%a") if opened else None,
        })
    trades.sort(key=lambda t: t.get("closed") or "")
    return trades


def stats(trades):
    if not trades:
        return {"trades": 0}
    pnls = [t["net"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    streak_win = streak_loss = 0
    best_streak_w = best_streak_l = 0
    for p in pnls:
        if p > 0:
            streak_win += 1
            streak_loss = 0
        elif p < 0:
            streak_loss += 1
            streak_win = 0
        best_streak_w = max(best_streak_w, streak_win)
        best_streak_l = max(best_streak_l, streak_loss)
    return {
        "trades": len(trades),
        "net": round(sum(pnls), 2),
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(-gross_loss, 2),
        "wins": len(wins), "losses": len(losses),
        "breakeven": len(pnls) - len(wins) - len(losses),
        "win_rate": round(len(wins) / len(pnls) * 100.0, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(pnls), 2),
        "largest_loss": round(min(pnls), 2),
        "max_drawdown": round(max_dd, 2),
        "max_win_streak": best_streak_w, "max_loss_streak": best_streak_l,
        "avg_duration_min": round(sum(t["duration_min"] or 0 for t in trades) / len(trades), 1),
        "total_volume": round(sum(t["volume"] for t in trades), 2),
        "commission": round(sum(t["commission"] for t in trades), 2),
        "swap": round(sum(t["swap"] for t in trades), 2),
        "first": trades[0].get("opened"), "last": trades[-1].get("closed"),
    }


def group(trades, key):
    out = {}
    for t in trades:
        bucket = t.get(key)
        if bucket is None:
            continue
        row = out.setdefault(str(bucket), {"trades": 0, "net": 0.0, "wins": 0})
        row["trades"] += 1
        row["net"] = round(row["net"] + t["net"], 2)
        row["wins"] += 1 if t["net"] > 0 else 0
    for row in out.values():
        row["win_rate"] = round(row["wins"] / row["trades"] * 100.0, 1) if row["trades"] else 0.0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Closed-trade stats from MT5 deal history.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--magic", type=int, default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--trades", action="store_true", help="list every trade")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    try:
        end = bridge_mod.now_utc()
        start = end - datetime.timedelta(days=a.days)
        deals = b.deals(start, end)
        trades = build_trades(deals)
        if a.symbol:
            trades = [t for t in trades if str(t["symbol"]).upper() == a.symbol.upper()]
        if a.magic is not None:
            trades = [t for t in trades if int(t.get("magic") or 0) == a.magic]

        report = {
            "generated": end.isoformat(), "mode": b.mode, "days": a.days,
            "account": {"login": b.account().get("login"),
                        "currency": b.account().get("currency"),
                        "balance": b.account().get("balance"),
                        "equity": b.account().get("equity")},
            "stats": stats(trades),
            "by_symbol": group(trades, "symbol"),
            "by_hour": group(trades, "hour"),
            "by_weekday": group(trades, "weekday"),
            "by_magic": group(trades, "magic"),
            "open_positions": b.positions(),
            "open_floating": round(sum(float(p.get("profit") or 0) for p in b.positions()), 2),
        }
        if a.trades:
            report["trades"] = trades
        if a.write:
            path = os.path.join(a.trader_dir, "state", "journal.json")
            bridge_mod.write_json(path, report)
            print("journal -> %s" % path)
        if a.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
        else:
            s = report["stats"]
            if not s.get("trades"):
                print("%d days: ma kaynch closed trades / no closed trades in %d days"
                      % (a.days, a.days))
            else:
                print("%d days, %d trades, net %.2f %s  (win rate %.1f%%, PF %s, expectancy %.2f)"
                      % (a.days, s["trades"], s["net"], report["account"]["currency"],
                         s["win_rate"], s["profit_factor"], s["expectancy"]))
                print("max drawdown %.2f | best streak %d | worst streak %d | avg hold %.0f min"
                      % (s["max_drawdown"], s["max_win_streak"], s["max_loss_streak"],
                         s["avg_duration_min"]))
                for sym, row in sorted(report["by_symbol"].items(),
                                       key=lambda kv: kv[1]["net"], reverse=True):
                    print("  %-8s %3d trades  net %8.2f  win %5.1f%%"
                          % (sym, row["trades"], row["net"], row["win_rate"]))
                print("  open: %d positions, floating %.2f"
                      % (len(report["open_positions"]), report["open_floating"]))
        return 0
    except BridgeError as e:
        print("JOURNAL ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
