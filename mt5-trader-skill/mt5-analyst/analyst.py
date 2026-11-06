#!/usr/bin/env python3
"""analyst.py - what a symbol is actually doing, in numbers you can size from.

Reads bars and quotes from MT5 (or the offline snapshot), then writes one row
per symbol to trader/metrics.json: ATR and ADR in pips, RSI, the EMA trend,
where today's range sits against its 20-day history, the spread you are
paying now versus the average, swaps, and a suggested stop/target pair.

    python3 analyst.py                        # every symbol in trader/symbols.json
    python3 analyst.py EURUSD XAUUSD          # just these
    python3 analyst.py --timeframe H1 --json
    python3 analyst.py --offline --write      # no terminal; writes trader/metrics.json

No indicator library, no pandas. Standard library only, so it runs next to a
MetaTrader terminal on Windows with nothing installed but MetaTrader5.
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


# ---------------------------------------------------------------- indicators

def ema(values, period):
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(float(v) * k + out[-1] * (1.0 - k))
    return out


def rsi(closes, period=14):
    """Wilder's RSI. Returns the last value, or None if not enough bars."""
    if len(closes) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = float(closes[i]) - float(closes[i - 1])
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def atr(bars, period=14):
    """Average true range (Wilder), in price terms."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        high, low, prev_close = float(bars[i]["high"]), float(bars[i]["low"]), float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def adr(bars, period=20):
    """Average daily range in price terms over the last N daily bars."""
    rows = bars[-period:] if period > 0 else bars
    if not rows:
        return None
    return sum(float(b["high"]) - float(b["low"]) for b in rows) / len(rows)


def percentile_of_last(values):
    """Where the newest value sits in the distribution of the previous ones (0-100)."""
    if len(values) < 3:
        return None
    last = float(values[-1])
    prev = [float(v) for v in values[:-1]]
    below = sum(1 for v in prev if v < last)
    return round(below / len(prev) * 100.0, 1)


def slope_pct(values, lookback=10):
    if len(values) < lookback + 1 or not values[0]:
        return None
    return round((values[-1] - values[-1 - lookback]) / abs(values[-1 - lookback]) * 100.0, 3)


def trend_label(ema_fast, ema_slow, price, min_gap_pct=0.05):
    if not ema_fast or not ema_slow or not price:
        return "unknown"
    gap = (ema_fast[-1] - ema_slow[-1]) / price * 100.0
    if abs(gap) < min_gap_pct:
        return "flat"
    return "up" if gap > 0 else "down"


# ---------------------------------------------------------------- per symbol

def symbol_metrics(b, symbol, cfg=None, timeframes=("H1", "D1"), bars=300):
    cfg = cfg or {}
    spec = b.spec(symbol)
    tick = b.tick(symbol)
    pip = sizing.pip_size(spec)
    point = sizing.point_size(spec)
    out = {
        "symbol": symbol, "digits": spec.get("digits"), "pip": pip,
        "price": round(float(tick.get("mid") or tick.get("bid") or 0.0), int(spec.get("digits", 5))),
        "bid": tick.get("bid"), "ask": tick.get("ask"),
        "spread_points": tick.get("spread_points"),
        "swap_long": spec.get("swap_long"), "swap_short": spec.get("swap_short"),
        "contract_size": spec.get("contract_size"),
        "volume_min": spec.get("volume_min"), "volume_step": spec.get("volume_step"),
        "value_per_point": round(sizing.value_per_point(spec), 6),
        "currency_base": spec.get("currency_base"), "currency_profit": spec.get("currency_profit"),
    }
    h1 = b.rates(symbol, "H1", bars)
    d1 = b.rates(symbol, "D1", min(bars, 260))

    if len(h1) > 20:
        closes = [float(x["close"]) for x in h1]
        h1_atr = atr(h1, 14)
        spreads = [float(x.get("spread") or 0) for x in h1[-100:]]
        out.update({
            "atr_h1_pips": round(h1_atr / pip, 1) if h1_atr else None,
            "rsi_h1": rsi(closes, 14),
            "ema20_h1": round(ema(closes, 20)[-1], int(spec.get("digits", 5))),
            "ema50_h1": round(ema(closes, 50)[-1], int(spec.get("digits", 5))),
            "trend_h1": trend_label(ema(closes, 20), ema(closes, 50), closes[-1]),
            "change_pct_h1": round((closes[-1] - closes[-2]) / closes[-2] * 100.0, 3) if closes[-2] else None,
            "avg_spread_points": int(sum(spreads) / len(spreads)) if spreads else None,
            "last_bar_time": h1[-1].get("time"),
        })
        rng = [float(x["high"]) - float(x["low"]) for x in h1[-24:]]
        out["last_24h_range_pips"] = round(sum(rng) / pip, 1) if rng else None
    if len(d1) > 25:
        d_closes = [float(x["close"]) for x in d1]
        d_atr = atr(d1, 14)
        daily_adr = adr(d1, 20)
        fast, slow = ema(d_closes, 50), ema(d_closes, 200)
        ranges = [float(x["high"]) - float(x["low"]) for x in d1]
        out.update({
            "atr_d1_pips": round(d_atr / pip, 1) if d_atr else None,
            "adr20_pips": round(daily_adr / pip, 1) if daily_adr else None,
            "trend_d1": trend_label(fast, slow, d_closes[-1]),
            "ema_gap_pct": round((fast[-1] - slow[-1]) / d_closes[-1] * 100.0, 3)
            if d_closes[-1] else None,
            "ema_slope_d1_pct": slope_pct(fast, 10),
            "today_range_pctile": percentile_of_last(ranges[-21:]) if len(ranges) >= 21 else None,
            "change_pct_d1": round((d_closes[-1] - d_closes[-2]) / d_closes[-2] * 100.0, 3)
            if len(d_closes) > 1 and d_closes[-2] else None,
        })
    # suggested stop/target: ATR-based, then checked against the broker's minimum
    atr_ref = out.get("atr_h1_pips") or out.get("atr_d1_pips") or cfg.get("default_stop_pips", 20)
    mult = float(cfg.get("stop_atr_multiple", 1.5))
    stop_pips = max(round(atr_ref * mult, 1), float(cfg.get("min_stop_pips", 5)))
    out["suggested_stop_pips"] = stop_pips
    out["suggested_tp_pips"] = round(stop_pips * float(cfg.get("min_reward_risk", 1.5)), 1)
    out["suggested_sl_price_buy"] = round_price(spec, float(out["price"]) - stop_pips * pip)
    out["suggested_sl_price_sell"] = round_price(spec, float(out["price"]) + stop_pips * pip)
    out["data_bars"] = {"H1": len(h1), "D1": len(d1)}
    return out


def round_price(spec, price):
    return round(float(price), int(spec.get("digits", 5)))


def _cell(value, width=7, digits=1):
    if value is None:
        return "%-*s" % (width, "-")
    if isinstance(value, float):
        return ("%*.*f" % (width, digits, value))
    return ("%*s" % (width, value))


def print_table(rows):
    """The report a human reads: is there a trend, is it volatile, is it cheap."""
    print("%-8s %-11s %-5s %-6s %-7s %-7s %-7s %-6s %-5s %-6s"
          % ("SYMBOL", "PRICE", "H1", "D1", "gap%", "ATR H1", "ADR20", "SPRD", "RSI", "STOPp"))
    print("-" * 82)
    for sym in sorted(rows):
        row = rows[sym]
        if row.get("error"):
            print("%-8s ERROR %s" % (sym, row["error"]))
            continue
        print("%-8s %-11s %-5s %-6s %-7s %-7s %-7s %-6s %-5s %-6s"
              % (sym,
                 ("%.*f" % (int(row.get("digits") or 5), float(row.get("price") or 0))),
                 (row.get("trend_h1") or "-")[:4],
                 (row.get("trend_d1") or "-")[:5],
                 _cell(row.get("ema_gap_pct"), 7, 3),
                 _cell(row.get("atr_h1_pips"), 7, 1),
                 _cell(row.get("adr20_pips"), 7, 1),
                 _cell(row.get("spread_points"), 6),
                 _cell(row.get("rsi_h1"), 5, 1),
                 _cell(row.get("suggested_stop_pips"), 6, 1)))
    print("-" * 82)
    print("gap% = EMA50 vs EMA200 on D1 (|gap| < 0.05 = flat). "
          "STOPp = suggested stop in pips.")


# ---------------------------------------------------------------- main

def load_symbols(path, cfg, cli_symbols):
    if cli_symbols:
        return list(cli_symbols)
    if path and os.path.exists(path):
        data = bridge_mod.read_json(path, {})
        if isinstance(data, list):
            return data
        if data.get("symbols"):
            return data["symbols"]
    if cfg.get("symbols"):
        return cfg["symbols"]
    raise SystemExit("ma kaynch symbols / no universe: pass symbols on the command line "
                     "or create trader/symbols.json (see mt5-core/symbols.example.json)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Symbol metrics: ATR, ADR, RSI, trend, spread, swaps.")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--symbols-file", default=None)
    ap.add_argument("--timeframe", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="write trader/metrics.json")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    cfg = b.cfg
    sym_file = a.symbols_file or os.path.join(a.trader_dir, "symbols.json")
    try:
        symbols = load_symbols(sym_file, cfg, a.symbols)
        rows = {}
        for sym in symbols:
            try:
                rows[sym] = symbol_metrics(b, sym, cfg)
            except BridgeError as e:
                rows[sym] = {"symbol": sym, "error": str(e)}
        payload = {
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": b.mode, "timeframe": a.timeframe or cfg.get("timeframe", "H1"),
            "account_currency": b.account().get("currency", "USD"),
            "symbols": rows,
        }
        if a.write:
            path = os.path.join(a.trader_dir, "metrics.json")
            bridge_mod.write_json(path, payload)
            print("metrics -> %s (%d symbols)" % (path, len(rows)))
        if a.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            print_table(rows)
        return 0
    except BridgeError as e:
        print("ANALYST ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
