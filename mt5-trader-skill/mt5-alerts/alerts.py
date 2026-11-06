#!/usr/bin/env python3
"""alerts.py - price, spread, session and margin alerts that ring once.

Checks every alert in trader/alerts.json against the live terminal (or the
offline snapshot), prints the ones that fired, and remembers what already fired
so it does not repeat every run. Put it on a schedule (Task Scheduler, cron,
Claude's schedule) and it becomes your watchman.

    python3 alerts.py                    # check everything, print what fired
    python3 alerts.py --json
    python3 alerts.py --reset            # forget what already fired
    python3 alerts.py --reset-id eur-1
    python3 alerts.py clock              # server time, sessions, next open/close

trader/alerts.json (see alerts.example.json):

    {"alerts": [
      {"id": "eur-1", "symbol": "EURUSD", "type": "price_above", "level": 1.0950},
      {"id": "gold",  "symbol": "XAUUSD", "type": "price_below", "level": 3900},
      {"id": "spr",   "symbol": "EURUSD", "type": "spread_above", "points": 25},
      {"id": "move",  "symbol": "GBPUSD", "type": "pips_move", "pips": 40, "window_min": 60},
      {"id": "mg",    "type": "margin_level_below", "level": 250},
      {"id": "lon",   "type": "session", "session": "london", "event": "open", "once": false}
    ]}

Supported types: price_above, price_below, spread_above, spread_below,
pips_move, margin_level_below, floating_profit_below, floating_profit_above,
session. Every alert takes "once": true (fire one time) and "cooldown_min".
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
Bridge = bridge_mod.Bridge
BridgeError = bridge_mod.BridgeError

# UTC sessions, the standard forex windows (DST shifts them by an hour)
SESSIONS = {
    "sydney": (21, 6), "tokyo": (0, 9), "london": (7, 16), "newyork": (12, 21),
}
SESSION_LABELS = {"sydney": "Sydney", "tokyo": "Tokyo", "london": "London", "newyork": "New York"}


def in_session(hour, name):
    start, end = SESSIONS[name]
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def session_state(now):
    hour = now.hour
    return {name: in_session(hour, name) for name in SESSIONS}


def session_boundaries(now):
    """Next open and close per session, in minutes from now."""
    out = {}
    for name, (start, end) in SESSIONS.items():
        for label, target in (("open", start), ("close", end)):
            delta_h = (target - now.hour) % 24
            minutes = delta_h * 60 - now.minute
            if minutes == 0:
                minutes = 1440
            out["%s_%s" % (name, label)] = minutes
    return out


def load_alerts(path):
    data = bridge_mod.read_json(path, None)
    if data is None:
        return []
    rows = data.get("alerts", data) if isinstance(data, dict) else data
    return [a for a in rows or [] if isinstance(a, dict)]


def load_state(path):
    data = bridge_mod.read_json(path, {}) or {}
    data.setdefault("fired", {})
    return data


def evaluate(alert, b, now):
    """(fired, message). Anything unreadable is a skip, never a crash."""
    kind = str(alert.get("type", "")).lower()
    symbol = alert.get("symbol")
    try:
        if kind in ("price_above", "price_below"):
            tick = b.tick(symbol)
            price = tick["mid"] or tick["bid"]
            level = float(alert["level"])
            if kind == "price_above":
                return price >= level, "%s %.5f >= %.5f" % (symbol, price, level)
            return price <= level, "%s %.5f <= %.5f" % (symbol, price, level)
        if kind in ("spread_above", "spread_below"):
            tick = b.tick(symbol)
            limit = float(alert["points"])
            spread = float(tick.get("spread_points") or 0)
            if kind == "spread_above":
                return spread > limit, "%s spread %.0f > %.0f points" % (symbol, spread, limit)
            return spread < limit, "%s spread %.0f < %.0f points" % (symbol, spread, limit)
        if kind == "pips_move":
            window = int(alert.get("window_min", 60))
            bars = b.rates(symbol, alert.get("timeframe", "M5"), max(20, window // 5 + 5))
            if not bars:
                return False, "%s: no bars" % symbol
            spec = b.spec(symbol)
            cutoff = now - datetime.timedelta(minutes=window)
            in_window = [x for x in bars if _bar_time(x) and _bar_time(x) >= cutoff] or bars[-1:]
            move = (float(in_window[-1]["close"]) - float(in_window[0]["open"]))
            pips = abs(move) / _pip(spec)
            return pips >= float(alert["pips"]), "%s moved %.1f pips in %d min" % (
                symbol, pips, window)
        if kind == "margin_level_below":
            acct = b.account()
            level = float(acct.get("margin_level") or 0)
            return 0 < level < float(alert["level"]), "margin level %.0f%% < %.0f%%" % (
                level, float(alert["level"]))
        if kind in ("floating_profit_below", "floating_profit_above"):
            floating = sum(float(p.get("profit") or 0) for p in b.positions())
            level = float(alert["level"])
            if kind == "floating_profit_below":
                return floating <= level, "floating %.2f <= %.2f" % (floating, level)
            return floating >= level, "floating %.2f >= %.2f" % (floating, level)
        if kind == "session":
            name = str(alert.get("session", "")).lower()
            event = str(alert.get("event", "open")).lower()
            if name not in SESSIONS:
                return False, "session ma3roufch / unknown session %r" % name
            is_open = in_session(now.hour, name)
            boundaries = session_boundaries(now)
            minutes = boundaries.get("%s_%s" % (name, event), 10 ** 6)
            fired = minutes <= int(alert.get("within_min", 5))
            return fired, "%s %s in %d min (open now: %s)" % (
                SESSION_LABELS[name], event, minutes, is_open)
    except BridgeError as e:
        return False, "%s: %s" % (symbol or "?", e)
    except (KeyError, TypeError, ValueError) as e:
        return False, "alert %r khass chi haja / malformed: %s" % (alert.get("id"), e)
    return False, "type ma3roufch / unknown type %r" % kind


def _bar_time(bar):
    value = bar.get("time")
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _pip(spec):
    point = float(spec.get("point") or 0.00001)
    return point * 10 if int(spec.get("digits", 5)) in (3, 5) else point


def cmd_clock(b, args):
    now = bridge_mod.now_utc()
    acct = b.account()
    server = now
    if b.mode == "live":
        tick = None
        for sym in ("EURUSD", "XAUUSD"):
            try:
                tick = b.tick(sym)
                break
            except BridgeError:
                continue
        if tick and tick.get("time"):
            server = datetime.datetime.fromtimestamp(float(tick["time"]), datetime.timezone.utc)
    payload = {
        "utc": now.isoformat(), "server_estimate": server.isoformat(),
        "server_offset_hours": round((server - now).total_seconds() / 3600.0, 2),
        "sessions": session_state(now),
        "next": session_boundaries(now),
        "market_open": any(session_state(now).values()) and now.weekday() < 5,
        "margin_level": acct.get("margin_level"),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("UTC %s | server ~%s (%+.1fh) | %s"
          % (now.strftime("%Y-%m-%d %H:%M"), server.strftime("%H:%M"),
             payload["server_offset_hours"],
             "OPEN" if payload["market_open"] else "closed / weekend"))
    for name, is_open in payload["sessions"].items():
        print("  %-8s %s  opens in %3d min, closes in %3d min"
              % (SESSION_LABELS[name], "OPEN  " if is_open else "closed",
                 payload["next"]["%s_open" % name], payload["next"]["%s_close" % name]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price, spread, session and margin alerts.")
    ap.add_argument("command", nargs="?", default="check", choices=["check", "clock"])
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--alerts", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--reset-id", default=None)
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    state_path = os.path.join(a.trader_dir, "state", "alerts.json")
    try:
        if a.command == "clock":
            return cmd_clock(b, a)
        state = load_state(state_path)
        if a.reset:
            state["fired"] = {}
            bridge_mod.write_json(state_path, state)
            print("alerts reset")
            return 0
        if a.reset_id:
            state["fired"].pop(a.reset_id, None)
            bridge_mod.write_json(state_path, state)
            print("reset %s" % a.reset_id)
            return 0

        alerts = load_alerts(a.alerts or os.path.join(a.trader_dir, "alerts.json"))
        if not alerts:
            print("ma kaynch alerts / no alerts: create trader/alerts.json "
                  "(see mt5-alerts/alerts.example.json)", file=sys.stderr)
            return 0
        now = bridge_mod.now_utc()
        fired, skipped, quiet = [], [], []
        for alert in alerts:
            aid = str(alert.get("id") or "%s-%s" % (alert.get("symbol"), alert.get("type")))
            alert["id"] = aid
            previous = state["fired"].get(aid) or {}
            if alert.get("once") and previous.get("fired_at"):
                skipped.append({"id": aid, "why": "once, already fired"})
                continue
            cooldown = float(alert.get("cooldown_min") or 0)
            if cooldown and previous.get("fired_at"):
                last = datetime.datetime.fromisoformat(previous["fired_at"])
                if (now - last).total_seconds() < cooldown * 60:
                    skipped.append({"id": aid, "why": "cooldown %d min" % cooldown})
                    continue
            did_fire, message = evaluate(alert, b, now)
            row = {"id": aid, "type": alert.get("type"), "symbol": alert.get("symbol"),
                   "message": message, "fired": did_fire}
            if did_fire:
                state["fired"][aid] = {"fired_at": now.isoformat(), "message": message,
                                       "count": int(previous.get("count") or 0) + 1}
                fired.append(row)
            else:
                quiet.append(row)
        bridge_mod.write_json(state_path, state)

        payload = {"generated": now.isoformat(), "mode": b.mode, "fired": fired,
                   "skipped": skipped, "quiet": quiet}
        if a.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            if not fired:
                print("ma kaynch alert fired / nothing fired (%d checked)" % len(quiet))
            for row in fired:
                print("ALERT %-10s %s" % (row["id"], row["message"]))
            for row in skipped:
                print("skip  %-10s %s" % (row["id"], row["why"]))
        return 1 if fired else 0
    except BridgeError as e:
        print("ALERTS ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
