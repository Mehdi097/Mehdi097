#!/usr/bin/env python3
"""bridge.py - the only file in this pack that talks to MetaTrader 5.

Everything else (sizing, risk, tickets, journal) is plain arithmetic on JSON
files, so it runs anywhere. This module is the one piece that needs the
Windows-only `MetaTrader5` package and a running terminal.

Two modes, same interface:

  live     the MetaTrader5 python package talks to your running terminal
  offline  reads a JSON snapshot (trader/data/snapshot.json). No terminal, no
           package, no orders. Used for tests, for a laptop without MT5, and
           for reviewing a setup before you go live.

    python3 bridge.py doctor                 # can we connect? which mode?
    python3 bridge.py account                # balance, equity, margin, demo/real
    python3 bridge.py spec EURUSD            # digits, tick value, lot step...
    python3 bridge.py tick EURUSD
    python3 bridge.py rates EURUSD H1 20
    python3 bridge.py positions
    python3 bridge.py symbols --search USD   # find the exact symbol names

Credentials come from environment variables only, never from JSON in the repo:
MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH. See SETUP.md.
"""

import argparse
import datetime
import json
import os
import sys

try:  # Windows only. Absence is normal on Mac/Linux/CI.
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the machine
    mt5 = None
    MT5_AVAILABLE = False

DEFAULTS = {
    "mode": "auto",                      # auto | live | offline
    "terminal_path": "",                 # C:\Program Files\MetaTrader 5\terminal64.exe
    "login": 0,                          # 0 = use the account already logged in
    "server": "",
    "timeout_ms": 60000,
    "portable": False,
    "signal_timeout": 10,
    "offline_snapshot": "trader/data/snapshot.json",
    "magic": 20261106,
    "deviation": 20,                     # max slippage, in points
    "retries": 3,
    "symbol_suffix": "",                 # e.g. ".raw" or "m" if your broker adds one
    "timeframe": "H1",
    "currency": "USD",
}

TF_MINUTES = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6, "M10": 10, "M12": 12,
    "M15": 15, "M20": 20, "M30": 30, "H1": 60, "H2": 120, "H3": 180, "H4": 240,
    "H6": 360, "H8": 480, "H12": 720, "D1": 1440, "W1": 10080, "MN1": 43200,
}

# ENUM_ORDER_TYPE, hard-coded so offline mode needs no package
ORDER_TYPE_CODE = {
    "buy": 0, "sell": 1, "buy_limit": 2, "sell_limit": 3,
    "buy_stop": 4, "sell_stop": 5, "buy_stop_limit": 6, "sell_stop_limit": 7,
}
TYPE_CODE = {"market": 0, "limit": 1, "stop": 2, "stop_limit": 3, "close": 4}

RETCODES = {
    10004: "requote", 10006: "rejected", 10007: "canceled", 10008: "placed",
    10009: "done", 10010: "partial", 10011: "error", 10012: "timeout",
    10013: "invalid request", 10014: "invalid volume", 10015: "invalid price",
    10016: "invalid stops", 10017: "trade disabled", 10018: "market closed",
    10019: "not enough money", 10020: "prices changed", 10021: "no quotes",
    10022: "invalid expiration", 10023: "order changed", 10024: "too many requests",
    10025: "no changes", 10026: "autotrading disabled by server",
    10027: "autotrading disabled in terminal", 10028: "locked",
    10029: "frozen", 10030: "invalid filling", 10031: "no connection",
    10033: "unsupported filling", 10034: "prohibited operation",
    10036: "position closed", 10038: "close volume mismatch", 10044: "close only",
}
OK_RETCODES = (10008, 10009, 10010)

BILINGUAL = {
    "no_pkg": (
        "`MetaTrader5` package ma msayebch / the MetaTrader5 python package is "
        "not installed.\n  Windows:  pip install MetaTrader5\n"
        "  Wla khdem b offline: python3 bridge.py --offline doctor"
    ),
    "no_terminal": (
        "MT5 ma mfto7ch wla l path ghalat / cannot open the terminal.\n"
        "  Halli MetaTrader 5, dkhel l compte demo, w 3mmer \"terminal_path\" f "
        "trader/config.json\n  (wla dir MT5_PATH f environment)."
    ),
    "no_symbol": "symbol ma kaynch f l'terminal / symbol not in Market Watch: %s",
}


class BridgeError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise BridgeError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def as_dict(obj):
    """namedtuple / struct / dict -> plain dict with python scalars."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _scalar(v) for k, v in obj.items()}
    if hasattr(obj, "_asdict"):
        try:
            return {k: _scalar(v) for k, v in obj._asdict().items()}
        except Exception:  # pragma: no cover
            pass
    out = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception:  # pragma: no cover
            continue
        if callable(v):
            continue
        out[k] = _scalar(v)
    return out


def _scalar(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def num(d, *keys, **kw):
    default = kw.get("default", 0.0)
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return float(default)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def load_config(trader_dir="trader", overrides=None):
    cfg = dict(DEFAULTS)
    path = os.path.join(trader_dir, "config.json")
    if os.path.exists(path):
        cfg.update(read_json(path, {}))
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def kill_switch(trader_dir="trader"):
    """One file stops everything: trader/state/KILL. No parsing, no excuses."""
    return os.path.exists(os.path.join(trader_dir, "state", "KILL"))


def timeframe_code(tf):
    tf = str(tf or "H1").upper()
    if tf.isdigit():
        return int(tf)
    if MT5_AVAILABLE:
        code = getattr(mt5, "TIMEFRAME_" + tf, None)
        if code is not None:
            return code
    if tf not in TF_MINUTES:
        raise BridgeError("timeframe ma3roufch / unknown timeframe: %s" % tf)
    return TF_MINUTES[tf]


def retcode_name(code):
    return RETCODES.get(int(code), "retcode %s" % code)


def build_request(order, spec, tick, cfg=None):
    """Turn our order JSON into the exact dict mt5.order_send wants.

    order: {symbol, side, volume, type, price, sl, tp, deviation, magic,
            comment, time_in_force, position}
    Prices are rounded to the symbol digits, volume is already normalised.
    """
    cfg = cfg or DEFAULTS
    symbol = order["symbol"]
    side = str(order.get("side", "")).lower()
    otype = str(order.get("type", "market")).lower()
    digits = int(spec.get("digits", 5))
    volume = round(float(order["volume"]), 8)

    if side not in ("buy", "sell"):
        raise BridgeError("side khass tkoun buy wla sell / side must be buy or sell: %r" % side)
    if otype not in TYPE_CODE or otype == "close":
        raise BridgeError("order type ma3roufch / unknown order type: %r" % otype)

    if side == "buy":
        mt5_type = {"market": "buy", "limit": "buy_limit", "stop": "buy_stop",
                    "stop_limit": "buy_stop_limit"}[otype]
        quote = tick.get("ask") if otype == "market" else order.get("price")
    else:
        mt5_type = {"market": "sell", "limit": "sell_limit", "stop": "sell_stop",
                    "stop_limit": "sell_stop_limit"}[otype]
        quote = tick.get("bid") if otype == "market" else order.get("price")

    req = {
        "action": 1 if otype == "market" else 5,   # TRADE_ACTION_DEAL / _PENDING
        "symbol": symbol,
        "volume": volume,
        "type": ORDER_TYPE_CODE[mt5_type],
        "deviation": int(order.get("deviation", cfg.get("deviation", 20))),
        "magic": int(order.get("magic", cfg.get("magic", 0))),
        "comment": str(order.get("comment", ""))[:31],
        "type_time": 0,                            # ORDER_TIME_GTC
    }
    if otype == "market":
        req["price"] = float(quote)
        if order.get("position"):
            req["position"] = int(order["position"])
    else:
        if quote is None:
            raise BridgeError("pending order bla price / pending order needs a price")
        req["price"] = round(float(quote), digits)
        if str(order.get("time_in_force", "gtc")).lower() == "day":
            req["type_time"] = 1                  # ORDER_TIME_DAY

    for key, field in (("sl", "sl"), ("tp", "tp")):
        if order.get(key) not in (None, 0, 0.0, ""):
            req[field] = round(float(order[key]), digits)

    if otype == "market":
        if int(spec.get("filling_mode_mask", 1)) & 1:
            req["type_filling"] = 0               # ORDER_FILLING_FOK
        elif int(spec.get("filling_mode_mask", 2)) & 2:
            req["type_filling"] = 1               # ORDER_FILLING_IOC
        else:
            req["type_filling"] = 2               # ORDER_FILLING_RETURN
    else:
        req["type_filling"] = 2                   # RETURN is right for pending orders

    if order.get("type_filling") is not None:
        req["type_filling"] = int(order["type_filling"])
    return req


def request_fingerprint(req):
    import hashlib
    keep = {k: req.get(k) for k in ("symbol", "type", "volume", "price", "sl", "tp", "magic")}
    blob = json.dumps(keep, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- the bridge

class Bridge(object):
    """Lazy connection. Nothing happens until the first call that needs MT5."""

    def __init__(self, trader_dir="trader", config=None, offline=None, verbose=False):
        self.root = trader_dir or "trader"
        self.cfg = load_config(self.root, config)
        self.verbose = verbose
        self._live = None
        self._snap = None
        self._connected = False
        self.warnings = []
        if offline is not None:
            self.mode = "offline" if offline else "live"
        elif self.cfg.get("mode") in ("offline", "live"):
            self.mode = self.cfg["mode"]
        else:
            snap = self._snapshot_path()
            self.mode = "offline" if (not MT5_AVAILABLE and os.path.exists(snap)) else "live"
        if self.mode == "live" and not MT5_AVAILABLE:
            # explicit live request without the package: fail loudly, not silently
            self.mode = "live"

    # -- offline snapshot -------------------------------------------------
    def _snapshot_path(self):
        """Where the offline snapshot is, whether the path is absolute, relative
        to the CWD, or relative to the trader folder (the exe runs from anywhere)."""
        raw = self.cfg.get("offline_snapshot") or ""
        candidates = []
        if raw:
            candidates.append(raw)
            if not os.path.isabs(raw):
                candidates.append(os.path.join(self.root, raw))
                candidates.append(os.path.join(self.root, os.path.basename(raw)))
        candidates.append(os.path.join(self.root, "data", "snapshot.json"))
        for cand in candidates:
            if cand and os.path.exists(cand):
                return cand
        return candidates[0]

    # -- connection -------------------------------------------------------
    def _connect(self):
        if self._connected:
            return
        if self.mode == "offline":
            path = self._snapshot_path()
            snap = read_json(path)
            if snap is None:
                raise BridgeError(
                    "offline mode w l'snapshot ma kaynch / offline mode but no snapshot at %s\n"
                    "  sjjel wa7ed b: python3 bridge.py snapshot --write" % path)
            self._snap = snap
            self._connected = True
            return
        if not MT5_AVAILABLE:
            raise BridgeError(BILINGUAL["no_pkg"])
        kwargs = {}
        path = self.cfg.get("terminal_path") or os.environ.get("MT5_PATH") or ""
        if path and os.path.exists(path):
            kwargs["path"] = path
        elif path:
            self.warnings.append("terminal_path ma kaynch / path does not exist: %s" % path)
        login = int(self.cfg.get("login") or os.environ.get("MT5_LOGIN") or 0)
        password = os.environ.get("MT5_PASSWORD") or ""
        server = self.cfg.get("server") or os.environ.get("MT5_SERVER") or ""
        if login and password:
            kwargs.update({"login": login, "password": password,
                           "server": server or None, "timeout": int(self.cfg.get("timeout_ms", 60000))})
        kwargs["portable"] = bool(self.cfg.get("portable", False))
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        ok = mt5.initialize(**kwargs)
        if not ok:
            code, msg = mt5.last_error()
            raise BridgeError(BILINGUAL["no_terminal"] + "\n  last_error: %s %s" % (code, msg))
        self._connected = True
        info = as_dict(mt5.terminal_info())
        if info and not info.get("trade_allowed", True):
            self.warnings.append(
                "Algo Trading m7bous f l'terminal / AutoTrading is OFF - order_send will fail. "
                "Klik 3la l'boton AutoTrading.")
        acct = self.account()
        if acct.get("is_real") and not self.cfg.get("allow_live", False):
            self.warnings.append(
                "Hada compte REAL / this is a REAL account. Order yt9der yt9bel ghir ila "
                "\"allow_live\": true f trader/config.json.")

    def shutdown(self):
        if self.mode == "live" and self._connected and MT5_AVAILABLE:
            try:
                mt5.shutdown()
            except Exception:  # pragma: no cover
                pass
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()
        return False

    def last_error(self):
        if MT5_AVAILABLE and self.mode == "live":
            return mt5.last_error()
        return (0, "offline")

    # -- account ----------------------------------------------------------
    def account(self):
        self._connect()
        if self.mode == "offline":
            return dict(self._snap.get("account", {}))
        raw = as_dict(mt5.account_info())
        if not raw:
            raise BridgeError("account_info khawi / empty - terminal ma connectach?")
        server = str(raw.get("server", ""))
        mode = raw.get("trade_mode", 0)
        return {
            "login": raw.get("login"), "name": raw.get("name"), "server": server,
            "currency": raw.get("currency", "USD"), "balance": num(raw, "balance"),
            "equity": num(raw, "equity"), "margin": num(raw, "margin"),
            "margin_free": num(raw, "margin_free"), "margin_level": num(raw, "margin_level"),
            "profit": num(raw, "profit"), "leverage": int(num(raw, "leverage", default=1)),
            "trade_mode": mode, "margin_mode": raw.get("margin_mode", 0),
            "trade_allowed": bool(raw.get("trade_allowed", True)),
            "is_real": mode == 2 or ("demo" not in server.lower() and mode != 0),
            "raw": {k: raw[k] for k in ("company", "server", "login") if k in raw},
        }

    def terminal(self):
        self._connect()
        if self.mode == "offline":
            return {"mode": "offline", "trade_allowed": False, "connected": False}
        return as_dict(mt5.terminal_info())

    # -- symbols ----------------------------------------------------------
    def _find_symbol(self, name):
        if self.mode == "offline":
            symbols = self._snap.get("symbols", {})
            if name in symbols:
                return name
            suffix = self.cfg.get("symbol_suffix") or ""
            if suffix and (name + suffix) in symbols:
                return name + suffix
            raise BridgeError(BILINGUAL["no_symbol"] % name)
        info = mt5.symbol_info(name)
        candidate = name
        if info is None and self.cfg.get("symbol_suffix"):
            candidate = name + self.cfg["symbol_suffix"]
            info = mt5.symbol_info(candidate)
        if info is None:
            raise BridgeError(BILINGUAL["no_symbol"] % name)
        if not getattr(info, "visible", True):
            mt5.symbol_select(candidate, True)
            info = mt5.symbol_info(candidate)
            if info is None:
                raise BridgeError(BILINGUAL["no_symbol"] % candidate)
        return candidate

    def spec(self, symbol):
        self._connect()
        symbol = self._find_symbol(symbol)
        if self.mode == "offline":
            spec = dict(self._snap["symbols"][symbol].get("spec", {}))
            spec.setdefault("name", symbol)
            return spec
        info = mt5.symbol_info(symbol)
        raw = as_dict(info)
        point = num(raw, "point", default=0.00001) or 0.00001
        tick_size = num(raw, "trade_tick_size") or point
        tick_value = num(raw, "trade_tick_value")
        tick_value_loss = num(raw, "trade_tick_value_loss") or tick_value
        contract = num(raw, "trade_contract_size", default=0.0)
        digits = int(num(raw, "digits", default=5))
        stops = int(num(raw, "trade_stops_level", default=0))
        freeze = int(num(raw, "trade_freeze_level", default=0))
        pip = point * 10 if digits in (3, 5) else point
        value_per_point = (tick_value / (tick_size / point)) if tick_size > 0 else 0.0
        return {
            "name": symbol,
            "description": raw.get("description", ""),
            "path": raw.get("path", ""),
            "digits": digits,
            "point": point,
            "pip": pip,
            "tick_size": tick_size,
            "tick_value": tick_value,
            "tick_value_loss": tick_value_loss,
            "value_per_point": value_per_point,
            "contract_size": contract,
            "volume_min": num(raw, "volume_min", default=0.01),
            "volume_max": num(raw, "volume_max", default=100.0),
            "volume_step": num(raw, "volume_step", default=0.01) or 0.01,
            "stops_level_points": stops,
            "freeze_level_points": freeze,
            "spread_points": int(num(raw, "spread", default=0)),
            "filling_mode_mask": int(num(raw, "filling_mode", default=1) or 1),
            "currency_base": raw.get("currency_base", ""),
            "currency_profit": raw.get("currency_profit", ""),
            "currency_margin": raw.get("currency_margin", ""),
            "margin_initial": num(raw, "margin_initial"),
            "swap_long": num(raw, "swap_long"),
            "swap_short": num(raw, "swap_short"),
            "trade_mode": raw.get("trade_mode", 4),
            "session_deals": raw.get("session_deals", 0),
        }

    def symbols(self, search="", limit=0):
        self._connect()
        if self.mode == "offline":
            names = sorted(self._snap.get("symbols", {}))
        else:
            names = [s.name for s in (mt5.symbols_get() or [])]
        if search:
            needle = search.upper()
            names = [n for n in names if needle in n.upper()]
        names.sort()
        return names[:limit] if limit else names

    # -- quotes and bars --------------------------------------------------
    def tick(self, symbol):
        self._connect()
        symbol = self._find_symbol(symbol)
        if self.mode == "offline":
            tick = dict(self._snap["symbols"][symbol].get("tick", {}))
            tick["symbol"] = symbol
            return tick
        raw = as_dict(mt5.symbol_info_tick(symbol))
        if not raw:
            raise BridgeError("no tick for %s / ma kaynch tick" % symbol)
        spec = self.spec(symbol)
        bid, ask = num(raw, "bid"), num(raw, "ask")
        return {
            "symbol": symbol, "bid": bid, "ask": ask, "last": num(raw, "last"),
            "time": raw.get("time"), "time_msc": raw.get("time_msc"),
            "volume": num(raw, "volume"),
            "spread_points": int(round((ask - bid) / spec["point"])) if bid and ask else 0,
            "mid": (bid + ask) / 2.0 if bid and ask else 0.0,
        }

    def rates(self, symbol, timeframe="H1", count=300):
        self._connect()
        symbol = self._find_symbol(symbol)
        tf = str(timeframe).upper()
        if self.mode == "offline":
            bars = (self._snap["symbols"][symbol].get("rates", {}) or {}).get(tf, [])
            return [dict(b) for b in bars[-int(count):]]
        arr = mt5.copy_rates_from_pos(symbol, timeframe_code(tf), 0, int(count))
        if arr is None:
            raise BridgeError("copy_rates_from_pos NULL for %s %s: %s"
                              % (symbol, tf, self.last_error()))
        out = []
        for row in arr:
            d = as_dict(row)
            out.append({
                "time": d.get("time"), "open": num(d, "open"), "high": num(d, "high"),
                "low": num(d, "low"), "close": num(d, "close"),
                "tick_volume": int(num(d, "tick_volume")),
                "spread": int(num(d, "spread")), "real_volume": int(num(d, "real_volume")),
            })
        return out

    def digits(self, symbol):
        return int(self.spec(symbol).get("digits", 5))

    # -- exposure ---------------------------------------------------------
    def positions(self, symbol=None):
        self._connect()
        if self.mode == "offline":
            rows = [dict(p) for p in self._snap.get("positions", [])]
        else:
            rows = [as_dict(p) for p in (mt5.positions_get() or [])]
        out = []
        for p in rows:
            ptype = int(p.get("type", 0))
            out.append({
                "ticket": p.get("ticket"), "symbol": p.get("symbol"),
                "type": ptype, "side": "buy" if ptype == 0 else "sell",
                "volume": num(p, "volume"), "price_open": num(p, "price_open"),
                "price_current": num(p, "price_current"), "sl": num(p, "sl"),
                "tp": num(p, "tp"), "profit": num(p, "profit"),
                "swap": num(p, "swap"), "magic": p.get("magic"),
                "comment": p.get("comment", ""), "time": p.get("time"),
            })
        if symbol:
            out = [p for p in out if p["symbol"] == symbol]
        return out

    def pending(self):
        self._connect()
        if self.mode == "offline":
            return [dict(o) for o in self._snap.get("orders", [])]
        return [as_dict(o) for o in (mt5.orders_get() or [])]

    def deals(self, start=None, end=None):
        self._connect()
        if self.mode == "offline":
            return [dict(d) for d in self._snap.get("deals", [])]
        end = end or now_utc()
        start = start or (end - datetime.timedelta(days=30))
        # history_deals_get(date_from, date_to) is the whole API: there is no
        # history_select_range in the Python package (that is MQL5 only).
        rows = mt5.history_deals_get(start, end) or ()
        return [as_dict(d) for d in rows]

    def history_orders(self, start=None, end=None):
        self._connect()
        if self.mode == "offline":
            return [dict(o) for o in self._snap.get("history_orders", [])]
        end = end or now_utc()
        start = start or (end - datetime.timedelta(days=30))
        return [as_dict(o) for o in (mt5.history_orders_get(start, end) or ())]

    def margin(self, symbol, volume, side="buy", price=None):
        """Margin this order would use, in account currency.

        Live mode asks the terminal (order_calc_margin), which handles leverage,
        margin rates and currency conversion exactly. Offline mode can only do
        notional / leverage, so a JPY-quoted pair is off by the USDJPY rate and
        the number is a sanity check, not a decision.
        """
        self._connect()
        if self.mode == "offline":
            spec = self.spec(symbol)
            tick = self.tick(symbol)
            px = price or tick["ask"]
            acct = self.account()
            lev = max(1, int(acct.get("leverage", 100)))
            notional = float(volume) * spec.get("contract_size", 100000) * px
            return round(notional / lev, 2)
        spec = self.spec(symbol)
        tick = self.tick(symbol)
        px = price or (tick["ask"] if side == "buy" else tick["bid"])
        value = mt5.order_calc_margin(
            ORDER_TYPE_CODE["buy"] if side == "buy" else ORDER_TYPE_CODE["sell"],
            symbol, float(volume), float(px))
        return round(float(value), 2) if value is not None else -1.0

    # -- orders -----------------------------------------------------------
    def check(self, request):
        """Dry run. Never places anything."""
        self._connect()
        if self.mode == "offline":
            return {"retcode": 0, "margin": self.margin(request["symbol"], request["volume"],
                                                        "buy" if request["type"] == 0 else "sell",
                                                        request.get("price")),
                    "margin_free": self.account().get("margin_free", 0.0),
                    "comment": "offline check", "request": request}
        res = as_dict(mt5.order_check(request))
        res.setdefault("request", request)
        return res

    def send(self, request, retries=None, simulate=None):
        """order_send with filling-mode fallback and requote retries.

        Returns the broker's result dict plus "ok" and "retcode_name".
        In offline mode it returns a simulated DONE and records the fill under
        trader/state/sim_fills.json so nothing pretends to be a real trade.
        """
        self._connect()
        retries = int(self.cfg.get("retries", 3) if retries is None else retries)
        if self.mode == "offline" or simulate:
            result = {
                "retcode": 10009, "retcode_name": "done",
                "order": 0, "deal": 0, "volume": request.get("volume"),
                "price": request.get("price"), "bid": request.get("price"),
                "ask": request.get("price"), "comment": "SIMULATED (offline)",
                "simulated": True, "ok": True, "request": request,
            }
            path = os.path.join(self.root, "state", "sim_fills.json")
            log = read_json(path, []) or []
            log.append({"time": now_utc().isoformat(), "request": request})
            write_json(path, log)
            return result

        if kill_switch(self.root):
            raise BridgeError("KILL file kayn f trader/state/KILL / kill switch is on. Nothing is sent.")

        fillings = [request.get("type_filling", 2)]
        mask = int(self.spec(request["symbol"]).get("filling_mode_mask", 1))
        for bit, code in ((1, 0), (2, 1)):
            if mask & bit and code not in fillings:
                fillings.append(code)
        if 2 not in fillings:
            fillings.append(2)

        last = None
        for attempt in range(max(1, retries)):
            for fill in fillings:
                req = dict(request)
                req["type_filling"] = fill
                last = as_dict(mt5.order_send(req))
                if not last:
                    break
                code = int(last.get("retcode", 0))
                if code in OK_RETCODES:
                    last.update({"ok": True, "retcode_name": retcode_name(code),
                                 "request": req, "simulated": False})
                    return last
                if code in (10030, 10033):      # wrong filling: try the next one
                    continue
                if code == 10004:               # requote: refresh price and retry
                    break
                last.update({"ok": False, "retcode_name": retcode_name(code),
                             "request": req, "simulated": False})
                return last
            if last and int(last.get("retcode", 0)) == 10004:
                tick = self.tick(request["symbol"])
                if request["type"] == ORDER_TYPE_CODE["buy"]:
                    request["price"] = tick["ask"]
                elif request["type"] == ORDER_TYPE_CODE["sell"]:
                    request["price"] = tick["bid"]
                continue
            if last and int(last.get("retcode", 0)) in OK_RETCODES:
                break
            break
        if last is None:
            code, msg = self.last_error()
            last = {"retcode": code, "retcode_name": retcode_name(code), "comment": msg,
                    "ok": False, "request": request}
        last.setdefault("ok", int(last.get("retcode", 0)) in OK_RETCODES)
        last.setdefault("retcode_name", retcode_name(last.get("retcode", 0)))
        last["request"] = request
        return last

    def close(self, ticket, deviation=None, comment="mt5-close"):
        """Close one open position by ticket, at market."""
        self._connect()
        positions = [p for p in self.positions() if int(p["ticket"]) == int(ticket)]
        if not positions:
            raise BridgeError("position %s ma kaynch / no open position %s" % (ticket, ticket))
        pos = positions[0]
        tick = self.tick(pos["symbol"])
        spec = self.spec(pos["symbol"])
        req = {
            "action": 1, "symbol": pos["symbol"], "volume": pos["volume"],
            "type": ORDER_TYPE_CODE["sell"] if pos["side"] == "buy" else ORDER_TYPE_CODE["buy"],
            "position": int(ticket),
            "price": tick["bid"] if pos["side"] == "buy" else tick["ask"],
            "deviation": int(deviation if deviation is not None else self.cfg.get("deviation", 20)),
            "magic": int(pos.get("magic") or self.cfg.get("magic", 0)),
            "comment": str(comment)[:31], "type_time": 0,
        }
        mask = int(spec.get("filling_mode_mask", 1))
        req["type_filling"] = 0 if mask & 1 else (1 if mask & 2 else 2)
        return self.send(req)

    def snapshot(self, symbol_list=None, timeframes=("H1", "H4", "D1"), count=300):
        """Freeze what we see into trader/data/snapshot.json (offline mode / review)."""
        self._connect()
        names = symbol_list or (sorted(self._snap.get("symbols", {})) if self.mode == "offline"
                                else self.cfg.get("symbols") or self.symbols(limit=8))
        snap = {"generated": now_utc().isoformat(), "mode": self.mode,
                "account": self.account(), "symbols": {}}
        for name in names:
            entry = {"spec": self.spec(name), "tick": self.tick(name), "rates": {}}
            for tf in timeframes:
                try:
                    entry["rates"][tf] = self.rates(name, tf, count)
                except BridgeError:
                    entry["rates"][tf] = []
            snap["symbols"][name] = entry
        snap["positions"] = self.positions()
        try:
            snap["deals"] = self.deals()
        except BridgeError:
            snap["deals"] = []
        return snap

    # -- convenience ------------------------------------------------------
    def value_per_point(self, symbol):
        return float(self.spec(symbol).get("value_per_point") or 0.0)

    def summary(self):
        acct = self.account()
        return {
            "mode": self.mode, "login": acct.get("login"), "server": acct.get("server"),
            "currency": acct.get("currency"), "balance": acct.get("balance"),
            "equity": acct.get("equity"), "margin_free": acct.get("margin_free"),
            "margin_level": acct.get("margin_level"),
            "is_real": acct.get("is_real", False),
            "open_positions": len(self.positions()),
            "warnings": list(self.warnings),
        }


def connect(trader_dir="trader", config=None, offline=None):
    return Bridge(trader_dir=trader_dir, config=config, offline=offline)


# ---------------------------------------------------------------- CLI

def _print(obj):
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def main(argv=None):
    # Flags and command words are separated by hand: argparse cannot split
    # "spec EURUSD" reliably when --flags sit between or before them, which is
    # exactly what the .exe runner does (--trader-dir first, then the command).
    raw = list(sys.argv[1:] if argv is None else argv)
    value_flags = {"--trader-dir", "--count", "--search", "--limit"}
    flags, words = [], []
    i = 0
    while i < len(raw):
        token = raw[i]
        if token in value_flags and i + 1 < len(raw):
            flags.extend([token, raw[i + 1]])
            i += 2
            continue
        if token.startswith("-") and token != "-":
            flags.append(token)
            i += 1
            continue
        words.append(token)
        i += 1

    ap = argparse.ArgumentParser(
        description="MT5 bridge: doctor, account, specs, quotes, positions.",
        epilog="commands: doctor | account | summary | spec SYMBOL | tick SYMBOL | "
               "rates SYMBOL TF N | positions | pending | symbols [--search X] | "
               "snapshot --write | close TICKET")
    ap.add_argument("--trader-dir", default="trader")
    ap.add_argument("--offline", action="store_true", help="no terminal, read the snapshot")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--search", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(flags)

    commands = ("doctor", "account", "summary", "spec", "tick", "rates", "positions",
                "pending", "symbols", "snapshot", "close", "check")
    if words and words[0] in commands:
        a.command, a.args = words[0], words[1:]
    elif words:
        ap.error("command ma3roufch / unknown command: %s" % words[0])
    else:
        a.command, a.args = "doctor", []

    offline = True if a.offline else (False if a.live else None)
    b = Bridge(a.trader_dir, offline=offline)
    try:
        if a.command == "doctor":
            out = {"mode": b.mode, "package": MT5_AVAILABLE}
            try:
                out["summary"] = b.summary()
                out["terminal"] = b.terminal() if b.mode == "live" else {"mode": "offline"}
                if a.args:
                    out["symbols"] = {s: b.spec(s) for s in a.args}
            except BridgeError as e:
                out["error"] = str(e)
                _print(out)
                return 2
            out["warnings"] = b.warnings
            _print(out)
            return 0
        if a.command == "account":
            _print(b.account())
        elif a.command == "summary":
            _print(b.summary())
        elif a.command == "spec":
            _print(b.spec(a.args[0] if a.args else "EURUSD"))
        elif a.command == "tick":
            _print(b.tick(a.args[0] if a.args else "EURUSD"))
        elif a.command == "rates":
            sym = a.args[0] if a.args else "EURUSD"
            tf = a.args[1] if len(a.args) > 1 else "H1"
            _print(b.rates(sym, tf, a.count))
        elif a.command == "positions":
            _print(b.positions())
        elif a.command == "pending":
            _print(b.pending())
        elif a.command == "symbols":
            _print(b.symbols(search=a.search or (a.args[0] if a.args else ""), limit=a.limit))
        elif a.command == "close":
            if not a.args:
                print("usage: bridge.py close TICKET", file=sys.stderr)
                return 2
            _print(b.close(int(a.args[0])))
        elif a.command == "snapshot":
            syms = a.args or None
            snap = b.snapshot(syms)
            out = os.path.join(a.trader_dir, "data", "snapshot.json")
            if a.write:
                write_json(out, snap)
                print("snapshot -> %s (%d symbols)" % (out, len(snap["symbols"])))
            else:
                _print(snap)
        elif a.command == "check":
            print("check needs an order request; use trader-broker/execute.py", file=sys.stderr)
            return 2
        return 0
    except BridgeError as e:
        print("BRIDGE ERROR: %s" % e, file=sys.stderr)
        return 2
    finally:
        b.shutdown()


if __name__ == "__main__":
    sys.exit(main())
