#!/usr/bin/env python3
"""doctor.py - is this machine ready to trade MT5 from Python?

Run it first, on the machine that has MetaTrader 5. It checks, in order:
python, the MetaTrader5 package, the terminal path, the connection, whether
AutoTrading is on, whether the account is demo or real, then every symbol in
your universe: does the broker list it, what is the spread now, can your equity
carry even one minimum lot, which filling mode will the executor use.

    python doctor.py                    # the checklist
    python doctor.py --init             # create trader/config.json + symbols.json
    python doctor.py --json
    python doctor.py --offline           # check the pack without a terminal

Exit 0 when everything is OK, 1 when something needs fixing (it says what),
2 when the pack itself is broken.
"""

import argparse
import datetime
import importlib.util
import json
import os
import shutil
import sys


def _core(name):
    key = "mt5core_" + name
    if key in sys.modules:
        return sys.modules[key]
    here = os.path.dirname(os.path.abspath(__file__))
    # frozen (PyInstaller) or a normal checkout
    bundle = getattr(sys, "_MEIPASS", None)
    if not bundle and getattr(sys, "frozen", False):
        bundle = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [here, os.path.join(here, "..", "mt5-core"),
                  os.environ.get("MT5_TRADER_CORE", "")]
    if bundle:
        candidates[:0] = [os.path.join(bundle, "mt5-core"),
                          os.path.join(bundle, "..", "mt5-core"), bundle]
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
    raise SystemExit("mt5-core/%s.py not found" % name)


bridge_mod = _core("bridge")
sizing = _core("sizing")
Bridge = bridge_mod.Bridge
BridgeError = bridge_mod.BridgeError

HERE = os.path.dirname(os.path.abspath(__file__))


def suggest_symbols(b, name, limit=5):
    """Close matches in the terminal, so a wrong symbol name is a one-line fix."""
    tokens = [name.upper()]
    for cut in (2, 3, 4):
        tokens.append(name.upper()[:cut])
    found = []
    try:
        everything = b.symbols()
    except Exception:
        return found
    for token in tokens:
        for candidate in everything:
            if token and token in candidate.upper() and candidate not in found:
                found.append(candidate)
                if len(found) >= limit:
                    return found
    return found


def check(ok, label, detail="", level=None):
    """ok True/False/None(unknown) -> OK / FAIL / WARN line."""
    if ok is True:
        status = "OK  "
    elif ok is False:
        status = "FAIL" if (level or "fail") == "fail" else "WARN"
    else:
        status = "WARN"
    return {"status": status.strip(), "label": label, "detail": str(detail)}


def init_files(root):
    created = []
    os.makedirs(root, exist_ok=True)
    cfg_path = os.path.join(root, "config.json")
    if not os.path.exists(cfg_path):
        src = os.path.join(HERE, "config.example.json")
        if os.path.exists(src):
            shutil.copyfile(src, cfg_path)
            created.append(cfg_path)
    sym_path = os.path.join(root, "symbols.json")
    if not os.path.exists(sym_path):
        src = os.path.join(HERE, "symbols.example.json")
        if os.path.exists(src):
            shutil.copyfile(src, sym_path)
            created.append(sym_path)
    for sub in ("state", "data"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return created


def run(root, offline=False, init=False):
    rows = []
    created = init_files(root) if init else []
    rows.append(check(sys.version_info >= (3, 8), "python >= 3.8",
                      "%d.%d.%d" % sys.version_info[:3]))
    rows.append(check(bridge_mod.MT5_AVAILABLE, "MetaTrader5 package",
                      "import ok" if bridge_mod.MT5_AVAILABLE else
                      "pip install MetaTrader5 (Windows only)", level="warn"))

    b = Bridge(root, offline=True if offline else None)
    cfg = b.cfg
    path = cfg.get("terminal_path") or os.environ.get("MT5_PATH") or ""
    path_row = None
    if b.mode == "live":
        path_row = check(bool(path) and os.path.exists(path), "terminal_path",
                         path or "not set - set it in trader/config.json or MT5_PATH", level="warn")
        rows.append(path_row)
    rows.append(check(True, "mode", "%s%s" % (b.mode,
                                              " (no terminal by design)" if b.mode == "offline" else "")))

    acct = {}
    try:
        acct = b.account()
        rows.append(check(bool(acct), "account_info",
                          "%s @ %s" % (acct.get("login"), acct.get("server"))))
        real = bool(acct.get("is_real"))
        rows.append(check(
            not real, "demo account",
            ("REAL ACCOUNT - allow_live is %s" % cfg.get("allow_live", False)) if real
            else "demo / contest account", level="warn"))
        rows.append(check(acct.get("trade_allowed", True), "trading allowed on account",
                          acct.get("trade_allowed"), level="warn"))
        rows.append(check(float(acct.get("equity") or 0) > 0, "equity > 0",
                          "%.2f %s" % (float(acct.get("equity") or 0), acct.get("currency", ""))))
        if path_row is not None and path_row.get("status") == "WARN":
            # it connected anyway: the terminal that is already running is enough
            path_row["status"] = "OK"
            path_row["detail"] = ("not set - kansta3mlo terminal li mfto7 / "
                                  "using the terminal that is already running")
    except BridgeError as e:
        rows.append(check(False, "connection", str(e).splitlines()[0]))
        b.shutdown()
        return {"generated": bridge_mod.now_utc().isoformat(), "mode": b.mode,
                "checks": rows, "created": created, "account": {}, "symbols": {}}

    if b.mode == "live":
        term = b.terminal()
        allowed = bool(term.get("trade_allowed"))
        rows.append(check(
            allowed, "AutoTrading ON",
            "trade_allowed=True" if allowed
            else "trade_allowed=False - klik l'boton AutoTrading f l'terminal", level="warn"))
        rows.append(check(term.get("connected", False), "terminal connected to broker",
                          term.get("connected"), level="warn"))
        rows.append(check(bool(term.get("build")), "terminal build", term.get("build"), level="warn"))

    sym_path = os.path.join(root, "symbols.json")
    data = bridge_mod.read_json(sym_path, {}) or {}
    symbols = data.get("symbols", []) if isinstance(data, dict) else data
    rows.append(check(bool(symbols), "symbols.json",
                      "%d symbols" % len(symbols) if symbols else
                      "create trader/symbols.json (mt5-core/symbols.example.json)"))

    equity = float(acct.get("equity") or 0)
    per_symbol = {}
    for sym in symbols[:20]:
        try:
            spec = b.spec(sym)
            tick = b.tick(sym)
            pip = sizing.pip_size(spec)
            min_lot = float(spec.get("volume_min") or 0.01)
            margin = b.margin(sym, min_lot, "buy", tick.get("ask"))
            affordable = equity <= 0 or margin < 0 or margin < equity * 0.5
            stop_pips = float(cfg.get("default_stop_pips", 20))
            loss = (sizing.price_to_points(spec, stop_pips * pip)
                    * sizing.value_per_point(spec) * min_lot)
            margin_txt = "n/a (l'broker ma 7sebach)" if margin < 0 else "%.2f" % margin
            per_symbol[sym] = {
                "digits": spec.get("digits"), "pip": pip,
                "spread_points": tick.get("spread_points"),
                "volume_min": min_lot, "volume_step": spec.get("volume_step"),
                "value_per_point": round(sizing.value_per_point(spec), 6),
                "margin_min_lot": round(margin, 2),
                "loss_at_default_stop": round(loss, 2),
                "filling_mask": spec.get("filling_mode_mask"),
                "stops_level_points": spec.get("stops_level_points"),
                "affordable": affordable,
            }
            rows.append(check(True, "symbol %s" % sym,
                              "%d digits, spread %s pts, min lot %.2f = margin %s, "
                              "%.2f per point/lot, %.2f at a %.0f-pip stop"
                              % (spec.get("digits"), tick.get("spread_points"), min_lot,
                                 margin_txt, sizing.value_per_point(spec), loss, stop_pips)))
            if not affordable:
                rows.append(check(False, "symbol %s affordability" % sym,
                                  "min lot margin %.2f vs equity %.2f - too big"
                                  % (margin, equity), level="warn"))
        except BridgeError as e:
            guess = suggest_symbols(b, sym)
            detail = str(e).splitlines()[0]
            if guess:
                detail += "  |  9rib lih / closest in your terminal: %s" % ", ".join(guess)
            else:
                detail += "  |  walo 9rib / nothing similar: 7eyyed %s mn trader/symbols.json" % sym
            rows.append(check(False, "symbol %s" % sym, detail))
            per_symbol[sym] = {"error": str(e), "suggestions": guess}

    if b.mode == "live" and symbols:
        try:
            snap_path = os.path.join(root, "data", "snapshot.json")
            b.snapshot(symbols[:8])
            rows.append(check(True, "snapshot available",
                              "python bridge.py snapshot --write  (writes %s)" % snap_path,
                              level="warn"))
        except BridgeError:
            pass

    killed = bridge_mod.kill_switch(root)
    rows.append(check(
        not killed, "kill switch",
        "trader/state/KILL kayn / present - sending is blocked" if killed else "off",
        level="warn"))

    payload = {
        "generated": bridge_mod.now_utc().isoformat(), "mode": b.mode,
        "python": "%d.%d.%d" % sys.version_info[:3],
        "package": bridge_mod.MT5_AVAILABLE,
        "account": {k: acct.get(k) for k in ("login", "server", "currency", "balance",
                                             "equity", "leverage", "is_real", "margin_mode")},
        "config_path": os.path.join(root, "config.json"),
        "checks": rows, "symbols": per_symbol, "created": created,
        "warnings": b.warnings,
    }
    b.shutdown()
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Is this machine ready for MT5 python trading?")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="write trader/state/doctor.json")
    a = ap.parse_args(argv)

    payload = run(a.trader_dir, offline=a.offline, init=a.init)
    payload["trader_dir"] = os.path.abspath(a.trader_dir)
    if a.write or True:
        path = os.path.join(a.trader_dir, "state", "doctor.json")
        try:
            bridge_mod.write_json(path, payload)
        except OSError:
            pass
    if a.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print("mt5-trader-skill doctor - mode: %s" % payload["mode"])
        print("-" * 72)
        for row in payload["checks"]:
            print("%-4s %-34s %s" % (row["status"], row["label"], row["detail"]))
        for warning in payload.get("warnings") or []:
            print("WARN %s" % warning)
        if payload.get("created"):
            print("\ncreated: %s" % ", ".join(payload["created"]))
        fails = [r for r in payload["checks"] if r["status"] == "FAIL"]
        print("-" * 72)
        print("%d checks, %d fail, %d warn"
              % (len(payload["checks"]), len(fails),
                 len([r for r in payload["checks"] if r["status"] == "WARN"])))
        if fails:
            print("\n9bel ma tkhdem b flous 7a9i9iyin / before you trade real money:")
            for row in fails:
                print("  - %s: %s" % (row["label"], row["detail"]))
    fails = [r for r in payload["checks"] if r["status"] == "FAIL"]
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
