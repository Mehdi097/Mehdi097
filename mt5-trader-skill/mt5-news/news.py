#!/usr/bin/env python3
"""news.py - headlines that touch the currencies and symbols you trade.

Pulls RSS feeds (config: "news_feeds") and keeps only the items that name one
of your currencies, your symbols, or a short list of market movers (Fed, ECB,
CPI, NFP, rate decision...). Each item gets a timestamp, a source, a matched
keyword and a severity guess. Writes trader/news.json.

    python3 news.py --hours 24                 # everything in the last day
    python3 news.py --symbols EURUSD XAUUSD    # only what touches those
    python3 news.py --write                    # -> trader/news.json
    python3 news.py --offline                  # read trader/data/news.json

No key, no signup, no scraping: RSS only. A dead feed is skipped, not fatal.
"""

import argparse
import datetime
import email.utils
import html
import importlib.util
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET


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

CURRENCY_WORDS = {
    "USD": ["dollar", "fed", "fomc", "powell", "treasury", "usd", "united states", "nonfarm", "cpi"],
    "EUR": ["euro", "ecb", "lagarde", "eur", "eurozone", "euro area"],
    "GBP": ["pound", "sterling", "boe", "bailey", "gbp", "uk ", "britain"],
    "JPY": ["yen", "boj", "japan", "jpy", "ueda"],
    "CHF": ["franc", "snb", "swiss", "chf"],
    "AUD": ["aussie", "rba", "australia", "aud"],
    "NZD": ["kiwi", "rbnz", "new zealand", "nzd"],
    "CAD": ["loonie", "boc", "canada", "cad", "oil"],
    "CNY": ["yuan", "pboc", "china", "cny"],
    "XAU": ["gold", "bullion", "xau", "safe haven"],
}
SEVERITY_WORDS = {
    "high": ["crash", "plunge", "soar", "surge", "emergency", "default", "war", "invasion",
             "sanction", "intervention", "rate hike", "rate cut", "halt", "bankrupt"],
    "medium": ["cpi", "inflation", "payroll", "gdp", "unemployment", "decision", "speech",
               "tariff", "opec", "earnings", "guidance"],
}
TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return html.unescape(TAG_RE.sub("", text or "")).strip()


def parse_date(value):
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
        except ValueError:
            continue
    return None


def parse_feed(xml_text, source):
    """RSS 2.0 and Atom, without a feed library."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag not in ("item", "entry"):
            continue
        def pick(*names):
            for name in names:
                for child in node:
                    if child.tag.split("}")[-1].lower() == name:
                        return child.text or child.attrib.get("href") or ""
            return ""
        items.append({
            "title": clean(pick("title")),
            "summary": clean(pick("description", "summary", "content"))[:400],
            "link": pick("link", "id"),
            "published": pick("pubdate", "published", "updated", "date"),
            "source": source,
        })
    return items


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "mt5-trader-skill/1.0 (+https://github.com/)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def tag_item(item, currencies, symbols, extra_keywords):
    blob = (item.get("title", "") + " " + item.get("summary", "")).lower()
    matched, sev = set(), "low"
    for cur in currencies:
        for word in CURRENCY_WORDS.get(cur, [cur.lower()]):
            if word in blob:
                matched.add(cur)
                break
    for sym in symbols:
        if sym.lower() in blob:
            matched.add(sym.upper())
    for word in extra_keywords:
        if word.lower() in blob:
            matched.add(word.lower())
    for level, words in SEVERITY_WORDS.items():
        if any(w in blob for w in words):
            sev = level if level == "high" else sev
    return sorted(matched), sev


def main(argv=None):
    ap = argparse.ArgumentParser(description="Headlines for your currencies and symbols.")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--currencies", default="")
    ap.add_argument("--feed", action="append", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args(argv)

    b = Bridge(a.trader_dir, offline=True if a.offline else None)
    cfg = b.cfg
    symbols = a.symbols or cfg.get("symbols") or []
    sym_file = os.path.join(a.trader_dir, "symbols.json")
    if not a.symbols and os.path.exists(sym_file):
        data = bridge_mod.read_json(sym_file, {})
        symbols = data.get("symbols", symbols) if isinstance(data, dict) else data
    currencies = [c.strip().upper() for c in a.currencies.split(",") if c.strip()]
    if not currencies:
        currencies = [c.upper() for c in (cfg.get("news_currencies") or list(CURRENCY_WORDS))]
    feeds = a.feed or cfg.get("news_feeds") or []
    now = bridge_mod.now_utc()
    cutoff = now - datetime.timedelta(hours=a.hours)
    extra = ["rate decision", "fomc", "nonfarm", "cpi", "ecb", "boe", "boj", "tariff"]

    raw_items, failures = [], []
    if a.offline or (not feeds):
        snap = bridge_mod.read_json(os.path.join(a.trader_dir, "data", "news.json"), {})
        raw_items = snap.get("items", snap if isinstance(snap, list) else [])
    else:
        for url in feeds:
            try:
                raw_items.extend(parse_feed(fetch(url), url))
            except Exception as e:  # noqa: BLE001 - a bad feed is not a crash
                failures.append({"feed": url, "error": str(e)})

    items = []
    for item in raw_items:
        when = parse_date(item.get("published")) or now
        if when < cutoff:
            continue
        matched, severity = tag_item(item, currencies, symbols, extra)
        if not matched:
            continue
        items.append({
            "title": item.get("title"), "link": item.get("link"),
            "published": when.isoformat(), "source": item.get("source"),
            "matched": matched, "severity": severity,
            "summary": item.get("summary", ""),
        })
    items.sort(key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x["severity"]], x["published"]),
               reverse=False)
    items = items[:a.limit]

    payload = {
        "generated": now.isoformat(), "mode": b.mode, "hours": a.hours,
        "currencies": currencies, "symbols": symbols,
        "items": items, "feed_errors": failures,
        "counts": {"high": sum(1 for i in items if i["severity"] == "high"),
                   "medium": sum(1 for i in items if i["severity"] == "medium"),
                   "low": sum(1 for i in items if i["severity"] == "low")},
    }
    if a.write:
        path = os.path.join(a.trader_dir, "news.json")
        bridge_mod.write_json(path, payload)
        print("news -> %s (%d items, %d high)" % (path, len(items), payload["counts"]["high"]))
    if a.json or not a.write:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    b.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
