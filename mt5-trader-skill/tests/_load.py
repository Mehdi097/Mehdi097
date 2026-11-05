"""_load.py - load a script from a skill folder (folder names contain hyphens)."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
SNAPSHOT = os.path.join(FIX, "snapshot.json")


_CACHE = {}


def load(folder, name):
    """Load a skill script once per path.

    Skills import their siblings by path too. Returning the SAME module object
    keeps exception classes identical, which is what lets a skill's
    `except BridgeError` catch what the bridge actually raised.
    """
    path = os.path.abspath(os.path.join(ROOT, folder, name + ".py"))
    key = "mt5core_" + name
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def make_trader(tmpdir, symbols=None, positions=None, config=None, targets=None,
                orders=None, deals="keep", risk=None):
    """Build a temporary trader/ folder wired to the offline snapshot."""
    root = os.path.join(tmpdir, "trader")
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)

    snap = read_json(SNAPSHOT)
    snap["generated"] = "2026-11-06T12:00:00+00:00"
    if positions is not None:
        snap["positions"] = positions
    if symbols is not None:
        keep = {k: v for k, v in snap["symbols"].items() if k in symbols}
        snap["symbols"] = keep
    if deals == "none":
        snap["deals"] = []
    write_json(os.path.join(root, "data", "snapshot.json"), snap)

    cfg = {
        "mode": "offline",
        "offline_snapshot": os.path.join(root, "data", "snapshot.json"),
        "magic": 20261106, "deviation": 20,
        "account_currency": "USD",
        "portfolio_risk_pct": 3.0, "risk_pct_per_trade": 0.5,
        "max_risk_pct_per_trade": 1.0,
        "default_stop_pips": 20, "default_tp_pips": 40,
        "max_lots_per_order": 1.0, "max_total_lots": 3.0,
        "max_open_positions": 6, "max_positions_per_symbol": 1,
        "max_orders_per_day": 10, "max_daily_loss_pct": 2.0,
        "max_drawdown_pct": 10.0, "min_margin_level_pct": 300,
        "max_spread_points": 30, "min_reward_risk": 1.5,
        "require_sl": True, "allow_short": True, "allow_pending": True,
        "allow_live": False, "allow_min_lot": False,
        "news_blackout_minutes": 30, "blocked_symbols": [], "allowed_symbols": [],
        "blocked_hours_utc": [],
    }
    if config:
        cfg.update(config)
    write_json(os.path.join(root, "config.json"), cfg)
    write_json(os.path.join(root, "symbols.json"), {
        "timeframe": "H1", "timeframes": ["H1", "D1"], "bars": 300,
        "symbols": sorted(snap["symbols"].keys()),
    })
    if targets is not None:
        write_json(os.path.join(root, "targets.json"), targets)
    if orders is not None:
        write_json(os.path.join(root, "orders.json"),
                   orders if isinstance(orders, dict) else {"orders": orders})
    if risk is not None:
        write_json(os.path.join(root, "state", "risk.json"), risk)
    return root


def bridge_for(root):
    core = load("mt5-core", "bridge")
    return core.Bridge(root, offline=True)


def cleanup(path):
    shutil.rmtree(path, ignore_errors=True)


def run(module, argv):
    """Call a skill's main() with its output swallowed, returning the exit code."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return module.main(argv)
