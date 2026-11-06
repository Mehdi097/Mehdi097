#!/usr/bin/env python3
"""copy.py - copy somebody's book into target weights your account can trade.

Sources it understands:

  1. a JSON or CSV statement you export from anywhere (Myfxbook, a prop firm,
     your old broker, a signal provider's published positions)
  2. your own open positions, renormalised - "keep the shape, resize it"
  3. a plain list of weights you type yourself

It maps what it finds to the symbols YOUR broker lists (suffixes included),
drops anything it cannot price, and writes trader/targets.json - the same file
mt5-screener writes, so mt5-budget does not care where the idea came from.

    python3 copy.py statement source.csv --top 5 --write
    python3 copy.py statement source.json --write
    python3 copy.py positions --top 4 --write
    python3 copy.py manual --weights EURUSD=30,GBPUSD=25,XAUUSD=20 --write
    python3 copy.py diff                       # where am I versus my targets?

source.csv needs a header like: symbol,side,volume   (price is optional)
source.json:
    {"source": "somebody", "positions": [{"symbol": "EURUSD", "side": "buy",
      "volume": 0.5, "price": 1.0850}]}
    or {"weights": {"EURUSD": 30, "XAUUSD": 20}}
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


class CopyError(Exception):
    pass


def read_csv_positions(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    if not lines:
        return rows
    header = [c.strip().lower() for c in lines[0].replace(";", ",").split(",")]
    has_header = any(h in ("symbol", "ticker", "pair", "instrument") for h in header)
    body = lines[1:] if has_header else lines
    for line in body:
        parts = [p.strip() for p in line.replace(";", ",").split(",")]
        if len(parts) < 2:
            continue
        symbol = parts[0].upper()
        side = "buy"
        volume = None
        for part in parts[1:]:
            low = part.lower()
            if low in ("buy", "long", "b"):
                side = "buy"
            elif low in ("sell", "short", "s"):
                side = "sell"
            else:
                try:
                    value = float(part)
                except ValueError:
                    continue
                if volume is None:
                    volume = value
        if volume is None or volume <= 0:
            continue
        rows.append({"symbol": symbol, "side": side, "volume": volume})
    return rows


def read_json_positions(path):
    data = bridge_mod.read_json(path, None)
    if data is None:
        raise CopyError("source ma kaynch / cannot read %s" % path)
    if isinstance(data, dict) and data.get("weights"):
        return [{"symbol": str(k).upper(), "side": "buy", "weight": float(v)}
                for k, v in data["weights"].items()]
    rows = data.get("positions", data) if isinstance(data, dict) else data
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        out.append({
            "symbol": str(row["symbol"]).upper(),
            "side": str(row.get("side") or row.get("type") or "buy").lower(),
            "volume": row.get("volume", row.get("lots", row.get("qty"))),
            "weight": row.get("weight"),
            "price": row.get("price"),
        })
    return out


def resolve_symbol(b, symbol):
    """Match a foreign symbol to the broker's own name, suffix included."""
    try:
        return b.spec(symbol)["name"]
    except BridgeError:
        pass
    suffix = b.cfg.get("symbol_suffix") or ""
    if suffix:
        try:
            return b.spec(symbol + suffix)["name"]
        except BridgeError:
            pass
    base = symbol.split(".")[0].split("_")[0][:6]
    try:
        for name in b.symbols(search=base):
            if name.upper().startswith(base):
                return b.spec(name)["name"]
    except BridgeError:
        pass
    return None


def weights_from(rows, b):
    """Positions or weights -> normalised weights on the broker's symbols."""
    total = 0.0
    weighted, skipped = [], []
    for row in rows:
        symbol = resolve_symbol(b, row["symbol"])
        if not symbol:
            skipped.append({"symbol": row["symbol"], "reason": "machi f l'broker / not listed"})
            continue
        if row.get("weight") and not row.get("volume"):
            size = float(row["weight"])
            weight_basis = "given"
        else:
            size = float(row.get("volume") or 0)
            weight_basis = "volume"
        if size <= 0:
            continue
        if row.get("price"):
            size *= float(row["price"])
            weight_basis = "notional"
        weighted.append({"symbol": symbol, "side": row["side"], "size": size,
                         "basis": weight_basis, "source_symbol": row["symbol"]})
        total += size
    if total <= 0:
        raise CopyError("source khawi wla koulchi skipped / nothing usable in the source")
    for item in weighted:
        item["weight"] = round(item["size"] / total * 100.0, 4)
    return weighted, skipped


def targets_from_weights(items, cfg, top=None):
    items = sorted(items, key=lambda i: -i["weight"])
    if top:
        items = items[:int(top)]
    total = sum(i["weight"] for i in items) or 1.0
    targets = []
    for item in items:
        weight = round(item["weight"] / total * 100.0, 4)
        targets.append({
            "symbol": item["symbol"],
            "side": "buy" if item["side"] == "buy" else "sell",
            "weight": weight,
            "reason": "copycat: %s weight from source (%s basis)"
                      % (item.get("source_symbol", item["symbol"]), item["basis"]),
        })
    return targets


def cmd_diff(b, args):
    targets = bridge_mod.read_json(args.targets or os.path.join(args.trader_dir, "targets.json"), None)
    if not targets:
        raise CopyError("ma kaynch targets / no targets.json yet - run copycat first")
    rows = targets.get("targets", targets) if isinstance(targets, dict) else targets
    wanted = {str(r["symbol"]).upper(): r for r in rows if r.get("symbol")}
    positions = b.positions()
    have = {}
    for pos in positions:
        sign = 1 if pos["side"] == "buy" else -1
        have[pos["symbol"]] = have.get(pos["symbol"], 0) + sign * float(pos["volume"])
    out = []
    for sym in sorted(set(list(wanted) + list(have))):
        want = wanted.get(sym, {})
        out.append({
            "symbol": sym, "target_weight": want.get("weight"),
            "target_side": want.get("side"), "current_lots": round(have.get(sym, 0.0), 4),
            "action": ("open" if sym in wanted and sym not in have else
                       "close" if sym not in wanted and sym in have else "check side"),
        })
    print(json.dumps({"generated": bridge_mod.now_utc().isoformat(), "diff": out},
                     indent=2, sort_keys=True, default=str))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy a source book into target weights.")
    ap.add_argument("command", choices=["statement", "positions", "manual", "diff"])
    ap.add_argument("source", nargs="?", default=None)
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--targets", default=None)
    ap.add_argument("--weights", default="")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    try:
        if a.command == "diff":
            return cmd_diff(b, a)
        if a.command == "statement":
            if not a.source:
                raise CopyError("3tini l'file / pass the statement path")
            if a.source.lower().endswith(".json"):
                rows = read_json_positions(a.source)
            else:
                rows = read_csv_positions(a.source)
        elif a.command == "positions":
            rows = [{"symbol": p["symbol"], "side": p["side"], "volume": p["volume"],
                     "price": p["price_current"]} for p in b.positions()]
            if not rows:
                raise CopyError("ma kaynch positions / no open positions to copy")
        else:
            rows = []
            for chunk in a.weights.split(","):
                if "=" not in chunk:
                    continue
                sym, value = chunk.split("=", 1)
                rows.append({"symbol": sym.strip().upper(), "side": "buy",
                             "weight": float(value)})
            if not rows:
                raise CopyError("--weights khawi / pass EURUSD=30,GBPUSD=20")
        items, skipped = weights_from(rows, b)
        targets = targets_from_weights(items, b.cfg, a.top)
        payload = {
            "source": "copycat:%s" % a.command,
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "targets": targets, "skipped": skipped,
        }
        if a.write:
            path = os.path.join(a.trader_dir, "targets.json")
            bridge_mod.write_json(path, payload)
            payload["written_to"] = path
            print("targets -> %s (%d symbols)" % (path, len(targets)))
            for s in skipped:
                print("SKIP %s: %s" % (s["symbol"], s["reason"]), file=sys.stderr)
        if a.json or not a.write:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            for t in targets:
                print("%-8s %-4s %5.1f%%  %s" % (t["symbol"], t["side"], t["weight"], t["reason"]))
            print("\ndaba: mt5-budget size.py --write")
        return 0
    except (CopyError, BridgeError) as e:
        print("COPYCAT ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
