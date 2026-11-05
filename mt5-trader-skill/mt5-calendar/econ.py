#!/usr/bin/env python3
"""econ.py - economic events and the news blackout windows around them.

High-impact releases (NFP, CPI, FOMC, ECB, rate decisions) move price further
than any stop you can place, so this skill turns the calendar into blackout
windows that mt5-risk refuses to trade inside.

Three sources, first one that answers wins:

  1. MT5's own calendar (mt5.calendar_events_by_country_get and friends), if
     your build of the package has them and the terminal is connected.
  2. trader/data/calendar.json - a snapshot you drop in, or what this script
     wrote last time.
  3. a JSON URL in config.json ("calendar_url").

    python3 econ.py                        # events + blackout, next 48 hours
    python3 econ.py --hours 12 --impact high
    python3 econ.py --write                # -> trader/calendar.json (risk reads this)
    python3 econ.py --check EURUSD         # am I inside a blackout right now?
    python3 econ.py --mine                 # only currencies I trade

(The file is econ.py, not calendar.py, on purpose: a script named calendar.py
shadows the standard library module of the same name and breaks `import email`.)

Snapshot format (trader/data/calendar.json), also what --write produces:

    {"events": [{"time": "2026-11-06T13:30:00Z", "currency": "USD",
                 "title": "Nonfarm Payrolls", "impact": "high",
                 "forecast": "180K", "previous": "254K"}]}
"""

import argparse
import datetime
import email.utils
import importlib.util
import json
import os
import sys
import urllib.request


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

IMPACT_RANK = {"low": 0, "medium": 1, "high": 2, "holiday": 3}
DEFAULT_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "CNY"]


def parse_time(value):
    """Accepts ISO strings, epoch seconds and 'YYYY.MM.DD HH:MM'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return datetime.datetime.fromtimestamp(float(text), datetime.timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(text.replace("Z", "+0000") if fmt.endswith("%z") else text, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    try:
        dt = email.utils.parsedate_to_datetime(text)
        return dt.astimezone(datetime.timezone.utc) if dt else None
    except Exception:
        return None


def normalise_event(raw):
    if not isinstance(raw, dict):
        return None
    when = parse_time(raw.get("time") or raw.get("date") or raw.get("datetime"))
    if when is None:
        return None
    currency = str(raw.get("currency") or raw.get("country") or "").upper()
    impact = str(raw.get("impact") or raw.get("importance") or "medium").lower()
    if impact not in IMPACT_RANK:
        impact = {"1": "low", "2": "medium", "3": "high", "0": "low"}.get(impact, "medium")
    return {
        "time": when.isoformat(),
        "time_utc": when,
        "currency": currency,
        "title": str(raw.get("title") or raw.get("event") or raw.get("name") or "").strip(),
        "impact": impact,
        "forecast": raw.get("forecast"), "previous": raw.get("previous"),
    }


def read_snapshot(path):
    data = bridge_mod.read_json(path, None)
    if data is None:
        return []
    rows = data.get("events", data) if isinstance(data, dict) else data
    out = []
    for raw in rows or []:
        ev = normalise_event(raw)
        if ev:
            out.append(ev)
    return out


def read_url(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "mt5-trader-skill/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    rows = data.get("events", data) if isinstance(data, dict) else data
    return [ev for ev in (normalise_event(r) for r in rows or []) if ev]


def from_mt5(b, hours):
    """Native MT5 calendar, when the package exposes it. Silent when it does not."""
    mt5 = getattr(bridge_mod, "mt5", None)
    if b.mode != "live" or mt5 is None:
        return []
    start = bridge_mod.now_utc()
    end = start + datetime.timedelta(hours=hours)
    events = []
    for name in ("calendar_events_by_country_get", "calendar_events_by_currency_get"):
        fn = getattr(mt5, name, None)
        if fn is None:
            continue
        try:
            raw = fn(start, end)
        except Exception:
            continue
        for row in raw or []:
            d = bridge_mod.as_dict(row)
            events.append(normalise_event({
                "time": d.get("time"), "currency": d.get("currency"),
                "title": d.get("event_name") or d.get("name"),
                "impact": d.get("importance") or d.get("impact"),
                "forecast": d.get("forecast_value"), "previous": d.get("prev_value"),
            }))
    return [e for e in events if e]


def currencies_for(b, symbols):
    """USD, EUR... touched by a symbol, from the broker's own spec."""
    out = set()
    for sym in symbols:
        try:
            spec = b.spec(sym)
        except BridgeError:
            continue
        for key in ("currency_base", "currency_profit"):
            cur = (spec.get(key) or "").upper()
            if len(cur) == 3:
                out.add(cur)
        if not spec.get("currency_base"):
            # metals and indices: XAUUSD -> USD, US30 -> USD
            out.add("USD")
            if sym.upper().startswith("XAU"):
                out.add("XAU")
    return sorted(out)


def blackout_windows(events, minutes, impacts=("high",)):
    windows = []
    for ev in events:
        if ev["impact"] not in impacts:
            continue
        half = datetime.timedelta(minutes=minutes)
        windows.append({
            "currency": ev["currency"], "title": ev["title"], "impact": ev["impact"],
            "from": (ev["time_utc"] - half).isoformat(),
            "to": (ev["time_utc"] + half).isoformat(),
            "event_time": ev["time_utc"].isoformat(),
        })
    windows.sort(key=lambda w: w["from"])
    return windows


def inside_blackout(windows, when, currencies=None):
    hits = []
    for w in windows:
        start = parse_time(w["from"])
        end = parse_time(w["to"])
        if start <= when <= end:
            if currencies and w["currency"] not in currencies:
                continue
            hits.append(w)
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="Economic calendar + news blackout windows.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--impact", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--minutes", type=int, default=None, help="blackout half-width")
    ap.add_argument("--currencies", default="")
    ap.add_argument("--mine", action="store_true", help="only my symbols' currencies")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", default="", help="symbol: am I in a blackout now?")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    cfg = b.cfg
    now = bridge_mod.now_utc()
    minutes = a.minutes if a.minutes is not None else int(cfg.get("news_blackout_minutes", 30))
    symbols = cfg.get("symbols") or []
    sym_file = os.path.join(a.trader_dir, "symbols.json")
    if os.path.exists(sym_file):
        data = bridge_mod.read_json(sym_file, {})
        symbols = data.get("symbols", symbols) if isinstance(data, dict) else data

    wanted = [c.strip().upper() for c in a.currencies.split(",") if c.strip()]
    if a.mine and not wanted:
        wanted = currencies_for(b, symbols)
    if not wanted:
        wanted = [c.upper() for c in (cfg.get("news_currencies") or DEFAULT_CURRENCIES)]

    events, source = [], "none"
    try:
        events = from_mt5(b, a.hours)
        if events:
            source = "mt5"
    except BridgeError:
        events = []
    if not events:
        snap = os.path.join(a.trader_dir, "data", "calendar.json")
        events = read_snapshot(snap)
        if events:
            source = "snapshot"
    if not events and cfg.get("calendar_url"):
        try:
            events = read_url(cfg["calendar_url"])
            source = "url"
        except Exception as e:  # noqa: BLE001 - any network failure is just "no source"
            print("calendar_url ma khdmach / failed: %s" % e, file=sys.stderr)

    events = [e for e in events if e["currency"] in wanted or not e["currency"]]
    horizon = now + datetime.timedelta(hours=a.hours)
    events = [e for e in events if now - datetime.timedelta(hours=2) <= e["time_utc"] <= horizon]
    min_rank = IMPACT_RANK[a.impact]
    events = [e for e in events if IMPACT_RANK.get(e["impact"], 1) >= min_rank]
    events.sort(key=lambda e: e["time_utc"])

    windows = blackout_windows(events, minutes, ("high",) if IMPACT_RANK[a.impact] <= 2
                               else ("high", "holiday"))
    payload = {
        "generated": now.isoformat(), "source": source, "mode": b.mode,
        "currencies": wanted, "blackout_minutes": minutes,
        "events": [{k: v for k, v in e.items() if k != "time_utc"} for e in events],
        "blackouts": windows,
    }

    code = 0
    if a.check:
        try:
            curs = currencies_for(b, [a.check.upper()])
        except BridgeError:
            curs = wanted
        hits = inside_blackout(windows, now, curs)
        payload["check"] = {"symbol": a.check.upper(), "currencies": curs,
                            "inside": bool(hits), "hits": hits}
        code = 1 if hits else 0

    if a.write:
        path = os.path.join(a.trader_dir, "calendar.json")
        bridge_mod.write_json(path, payload)
        print("calendar -> %s (%d events, %d blackout windows, source %s)"
              % (path, len(events), len(windows), source))
    if a.json or not a.write:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    elif a.check:
        print("BLACKOUT" if payload["check"]["inside"] else "clear")
    b.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
