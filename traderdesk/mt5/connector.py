"""Connexion et exécution MetaTrader 5.

Trois modes :

* ``simulation`` — compte démo local, remplit les ordres instantanément.
  C'est le mode par défaut : on peut tout tester sans argent réel.
* ``rest``     — adresse + clé API d'une passerelle REST (le serveur
  ``traderdesk.mt5.bridge`` fourni, à lancer sur la machine Windows où le
  terminal MT5 est installé).
* ``local``    — package Python officiel ``MetaTrader5`` (Windows uniquement),
  avec login / mot de passe / serveur / chemin du terminal.

Aucun mode n'est autorisé à placer un ordre réel sans que le moteur ait
vérifié : kill switch, ``live_trading``, risk PASS du jour, plafonds.
"""

import json
import random
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_PRICES = {
    "AAPL": 341.27, "AXP": 309.84, "GOOGL": 353.78, "GOOG": 354.10,
    "KO": 90.11, "BAC": 53.96, "BRK.B": 512.40,
}


class MT5Error(Exception):
    pass


def _now():
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_address(address):
    a = (address or "").strip().rstrip("/")
    if not a:
        raise MT5Error("L'adresse de la passerelle est vide")
    if not a.startswith(("http://", "https://")):
        a = "http://" + a
    return a


class BaseConnector:
    mode = "base"
    label = "Non connecté"

    def __init__(self, cfg):
        self.cfg = cfg
        self.connected = False
        self.last_error = ""
        self.last_check = None
        self.latency_ms = 0
        self._lock = threading.RLock()

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        self.connected = False

    def ping(self):
        raise NotImplementedError

    def account(self):
        raise NotImplementedError

    def positions(self):
        return []

    def symbols(self):
        return []

    def place_order(self, **kw):
        raise NotImplementedError

    def close_position(self, ticket):
        raise NotImplementedError

    def history(self):
        return []

    def tick(self):
        pass


# --------------------------------------------------------------------------- simulation
class SimulationConnector(BaseConnector):
    """Compte démo : carnet d'ordres, positions, P/L et marche aléatoire des prix."""

    mode = "simulation"
    label = "Simulation · compte démo MT5"

    def __init__(self, cfg, initial_balance=10000.0):
        super().__init__(cfg)
        self.initial_balance = float(initial_balance)
        self.balance = self.initial_balance
        self.prices = dict(DEFAULT_PRICES)
        self._positions = {}
        self._history = []
        self._ticket = 900000
        self._rng = random.Random(20261106)

    def connect(self):
        self.connected = True
        self.last_error = ""
        self.last_check = _now()
        self.latency_ms = 1
        return {
            "mode": self.mode, "server": "TraderDesk-Demo", "account": "DEMO-001",
            "connected": True, "message": "Compte démo prêt (aucun ordre réel)",
        }

    def ping(self):
        return {"ok": True, "time": _now(), "server": "TraderDesk-Demo", "mode": self.mode}

    def _mark_price(self, symbol, price):
        self.prices[symbol] = round(max(0.01, float(price)), 4)

    def tick(self):
        with self._lock:
            for s, p in list(self.prices.items()):
                drift = self._rng.uniform(-0.0016, 0.0016)
                self._mark_price(s, p * (1 + drift))

    def quote(self, symbol):
        sym = self._map(symbol)
        return self.prices.get(sym, 100.0)

    def _map(self, symbol):
        return (self.cfg.get("symbol_map") or {}).get(symbol.upper(), symbol.upper())

    def account(self):
        with self._lock:
            market = sum(float(p["volume"]) * self.prices.get(p["symbol"], p["price_open"])
                         for p in self._positions.values())
            equity = self.balance + market
            profit = sum(
                float(p["volume"]) * (self.prices.get(p["symbol"], p["price_open"]) - p["price_open"])
                * (1 if p["side"] == "buy" else -1)
                for p in self._positions.values()
            )
            return {
                "login": "DEMO-001", "server": "TraderDesk-Demo", "currency": "USD",
                "balance": round(self.balance, 2), "equity": round(equity, 2),
                "margin": 0.0, "free_margin": round(self.balance, 2),
                "profit": round(profit, 2), "leverage": 100,
                "mode": "simulation", "connected": self.connected,
                "trade_allowed": True, "as_of": _now(),
            }

    def positions(self):
        with self._lock:
            out = []
            for t, p in self._positions.items():
                cur = self.prices.get(p["symbol"], p["price_open"])
                profit = (cur - p["price_open"]) * p["volume"] * (1 if p["side"] == "buy" else -1)
                out.append({
                    "ticket": t, "symbol": p["symbol"], "side": p["side"],
                    "volume": p["volume"], "price_open": p["price_open"],
                    "price_current": round(cur, 4), "sl": p.get("sl"), "tp": p.get("tp"),
                    "profit": round(profit, 2), "time": p["time"], "comment": p.get("comment", ""),
                })
            return out

    def symbols(self):
        return [{"symbol": s, "price": p, "bid": round(p - 0.02, 4), "ask": round(p + 0.02, 4),
                 "volume_min": 0.01, "volume_step": 0.01} for s, p in self.prices.items()]

    def place_order(self, symbol, side, volume, price=None, sl=None, tp=None,
                    comment="TraderDesk", magic=None, **kw):
        with self._lock:
            sym = self._map(symbol)
            vol = round(float(volume), 4)
            if vol <= 0:
                raise MT5Error("volume invalide : %s" % volume)
            fill = float(price) if price else self.prices.get(sym, 100.0)
            self._mark_price(sym, fill)
            self._ticket += 1
            ticket = self._ticket
            cost = vol * fill
            if side == "buy":
                self.balance -= cost
                key = "%s-buy" % sym
                if key in self._positions:
                    self._positions[key]["volume"] = round(self._positions[key]["volume"] + vol, 4)
                else:
                    self._positions[ticket] = {
                        "symbol": sym, "side": "buy", "volume": vol, "price_open": fill,
                        "time": _now(), "sl": sl, "tp": tp, "comment": comment,
                    }
            else:
                self.balance += cost
                left = vol
                for key in sorted(list(self._positions), key=lambda k: self._positions[k]["time"]):
                    p = self._positions[key]
                    if left <= 0:
                        break
                    if p["symbol"] != sym or p["side"] != "buy":
                        continue
                    take = min(left, p["volume"])
                    p["volume"] = round(p["volume"] - take, 4)
                    left = round(left - take, 4)
                    if p["volume"] <= 0:
                        self._positions.pop(key, None)
            rec = {
                "ticket": ticket, "retcode": 10009, "status": "filled", "symbol": sym,
                "side": side, "volume": vol, "price": round(fill, 4), "sl": sl, "tp": tp,
                "comment": comment, "magic": magic or self.cfg.get("magic", 240611),
                "time": _now(), "mode": self.mode,
            }
            self._history.append(rec)
            return rec

    def close_position(self, ticket):
        with self._lock:
            p = self._positions.pop(int(ticket), None)
            if not p:
                raise MT5Error("position %s introuvable" % ticket)
            price = self.prices.get(p["symbol"], p["price_open"])
            self.balance += p["volume"] * price
            return {"ticket": ticket, "status": "closed", "price": round(price, 4), "time": _now()}

    def history(self):
        return list(self._history[-100:])


# --------------------------------------------------------------------------- REST bridge
class RestConnector(BaseConnector):
    """Parle à une passerelle REST MT5 protégée par clé API."""

    mode = "rest"
    label = "Passerelle REST MT5 (adresse + clé API)"

    def __init__(self, cfg, api_key=""):
        super().__init__(cfg)
        self.address = normalize_address(cfg.get("address"))
        self.api_key = api_key
        self.timeout = float(cfg.get("timeout") or 8)

    def _request(self, method, path, payload=None, timeout=None):
        url = self.address + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("X-API-Key", self.api_key)
        req.add_header("Authorization", "Bearer " + self.api_key)
        req.add_header("User-Agent", "TraderDesk/1.0")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise MT5Error("HTTP %s %s — %s" % (e.code, e.reason, detail))
        except urllib.error.URLError as e:
            raise MT5Error("Passerelle injoignable (%s) : %s" % (self.address, e.reason))
        except Exception as e:  # noqa: BLE001
            raise MT5Error("Erreur réseau : %s" % e)
        self.latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError:
            return {"raw": body[:1000]}

    def connect(self):
        if not self.api_key:
            raise MT5Error("Clé API manquante : renseignez-la dans Connexion MT5")
        info = self._request("GET", "/api/v1/ping")
        if info.get("ok") is False:
            raise MT5Error(info.get("error") or "la passerelle a refusé la connexion")
        self.connected = True
        self.last_error = ""
        self.last_check = _now()
        return {"mode": self.mode, "server": info.get("server", self.address),
                "account": info.get("account", ""), "connected": True,
                "message": info.get("message", "Passerelle connectée"), "latency_ms": self.latency_ms}

    def ping(self):
        return self._request("GET", "/api/v1/ping")

    def account(self):
        d = self._request("GET", "/api/v1/account")
        d.update({"mode": self.mode, "connected": self.connected, "server": self.cfg.get("server") or self.address})
        return d

    def positions(self):
        d = self._request("GET", "/api/v1/positions")
        return d.get("positions", d if isinstance(d, list) else [])

    def symbols(self):
        d = self._request("GET", "/api/v1/symbols")
        return d.get("symbols", d if isinstance(d, list) else [])

    def place_order(self, symbol, side, volume, price=None, sl=None, tp=None,
                    comment="TraderDesk", magic=None, **kw):
        payload = {
            "symbol": symbol, "side": side, "volume": float(volume), "type": "market",
            "price": price, "sl": sl, "tp": tp, "comment": comment,
            "magic": magic or self.cfg.get("magic", 240611),
            "deviation": self.cfg.get("deviation", 20),
        }
        d = self._request("POST", "/api/v1/order", payload)
        if d.get("ok") is False or (d.get("retcode") not in (None, 10009, 10008, 0) and d.get("status") == "rejected"):
            raise MT5Error(d.get("error") or d.get("comment") or "ordre refusé par MT5")
        return d

    def close_position(self, ticket):
        return self._request("POST", "/api/v1/close", {"ticket": ticket})

    def history(self):
        d = self._request("GET", "/api/v1/history")
        return d.get("orders", d if isinstance(d, list) else [])


# --------------------------------------------------------------------------- local terminal
class LocalConnector(BaseConnector):
    """Utilise le package officiel MetaTrader5 (Windows + terminal installé)."""

    mode = "local"
    label = "Terminal MetaTrader 5 local"

    def __init__(self, cfg, password=""):
        super().__init__(cfg)
        self.password = password
        self.mt5 = None

    def _module(self):
        try:
            import MetaTrader5 as mt5  # type: ignore
            return mt5
        except ImportError:
            raise MT5Error(
                "Package MetaTrader5 absent. Sur Windows : pip install MetaTrader5, "
                "puis installez le terminal MT5."
            )

    def connect(self):
        mt5 = self._module()
        self.mt5 = mt5
        path = (self.cfg.get("terminal_path") or "").strip() or None
        if not mt5.initialize(path=path):
            raise MT5Error("mt5.initialize a échoué : %s" % mt5.last_error())
        login = str(self.cfg.get("account") or "").strip()
        server = str(self.cfg.get("server") or "").strip()
        if login and self.password and server:
            if not mt5.login(int(login), password=self.password, server=server):
                raise MT5Error("mt5.login a échoué : %s" % mt5.last_error())
        info = mt5.account_info()
        if info is None:
            raise MT5Error("Aucun compte connecté au terminal : %s" % mt5.last_error())
        self.connected = True
        self.last_error = ""
        self.last_check = _now()
        return {"mode": self.mode, "server": info.server, "account": str(info.login),
                "connected": True, "message": "Terminal MT5 connecté"}

    def ping(self):
        info = self.mt5.account_info() if self.mt5 else None
        if info is None:
            raise MT5Error("terminal déconnecté")
        return {"ok": True, "server": info.server, "account": str(info.login), "mode": self.mode}

    def account(self):
        i = self.mt5.account_info()
        if i is None:
            raise MT5Error("account_info indisponible")
        return {
            "login": str(i.login), "server": i.server, "currency": i.currency,
            "balance": i.balance, "equity": i.equity, "margin": i.margin,
            "free_margin": i.margin_free, "profit": i.profit, "leverage": i.leverage,
            "mode": self.mode, "connected": self.connected, "trade_allowed": True,
            "as_of": _now(),
        }

    def positions(self):
        rows = self.mt5.positions_get() or []
        return [{
            "ticket": p.ticket, "symbol": p.symbol,
            "side": "buy" if p.type == 0 else "sell", "volume": p.volume,
            "price_open": p.price_open, "price_current": p.price_current,
            "sl": p.sl, "tp": p.tp, "profit": p.profit, "time": str(p.time),
            "comment": p.comment,
        } for p in rows]

    def symbols(self):
        rows = self.mt5.symbols_get() or []
        return [{"symbol": s.name, "bid": s.bid, "ask": s.ask,
                 "volume_min": s.volume_min, "volume_step": s.volume_step} for s in rows[:300]]

    def place_order(self, symbol, side, volume, price=None, sl=None, tp=None,
                    comment="TraderDesk", magic=None, **kw):
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error("symbole %s introuvable dans MT5" % symbol)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": float(volume), "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if side == "buy" else tick.bid,
            "deviation": int(self.cfg.get("deviation") or 20),
            "magic": int(magic or self.cfg.get("magic") or 240611),
            "comment": comment[:30], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl:
            req["sl"] = float(sl)
        if tp:
            req["tp"] = float(tp)
        result = mt5.order_send(req)
        if result is None:
            raise MT5Error("order_send a renvoyé None : %s" % mt5.last_error())
        if result.retcode not in (mt5.TRADE_RETCODE_DONE, 10008, 10009):
            raise MT5Error("MT5 retcode %s : %s" % (result.retcode, result.comment))
        return {"ticket": result.order, "retcode": result.retcode, "status": "placed",
                "symbol": symbol, "side": side, "volume": float(volume),
                "price": result.price, "comment": result.comment, "time": _now(), "mode": self.mode}

    def close_position(self, ticket):
        mt5 = self.mt5
        pos = next((p for p in (mt5.positions_get() or []) if p.ticket == int(ticket)), None)
        if pos is None:
            raise MT5Error("position %s introuvable" % ticket)
        t = mt5.symbol_info_tick(pos.symbol)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
            "price": t.bid if pos.type == 0 else t.ask, "position": pos.ticket,
            "deviation": 20, "magic": int(self.cfg.get("magic") or 240611),
            "comment": "TraderDesk close", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        return {"ticket": ticket, "status": "closed" if r and r.retcode == mt5.TRADE_RETCODE_DONE else "failed"}

    def history(self):
        return []

    def disconnect(self):
        try:
            if self.mt5:
                self.mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.connected = False


# --------------------------------------------------------------------------- manager
class ConnectorManager:
    """Construit le bon connecteur à partir des réglages et garde son état."""

    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.connector = None
        self._lock = threading.RLock()

    def build(self, cfg=None):
        mt5 = (cfg or self.settings.get("mt5"))
        mode = mt5.get("mode", "simulation")
        if mode == "rest":
            return RestConnector(mt5, api_key=self.settings.secret("api_key"))
        if mode == "local":
            return LocalConnector(mt5, password=self.settings.secret("password"))
        budget = float(self.settings.get("trading").get("budget") or 5000)
        return SimulationConnector(mt5, initial_balance=budget)

    @property
    def current(self):
        with self._lock:
            return self.connector

    def connect(self, cfg=None):
        with self._lock:
            if self.connector:
                try:
                    self.connector.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            conn = self.build(cfg)
            mt5cfg = cfg or self.settings.get("mt5")
            info = conn.connect()
            self.connector = conn
            c = self.store.connection
            c.update({
                "state": "connected", "mode": conn.mode, "label": conn.label,
                "address": normalize_address(mt5cfg.get("address")) if conn.mode == "rest" else "",
                "server": info.get("server", ""), "account": str(info.get("account", "")),
                "last_check": _now(), "last_error": "", "latency_ms": conn.latency_ms,
                "message": info.get("message", ""), "attempts": c.get("attempts", 0) + 1,
                "next_retry": "",
            })
            self.store.save()
            return info

    def fail(self, exc, cfg=None):
        mt5cfg = cfg or self.settings.get("mt5")
        with self._lock:
            self.connector = None
            c = self.store.connection
            c.update({
                "state": "error", "mode": mt5cfg.get("mode", "simulation"),
                "address": mt5cfg.get("address", ""), "last_check": _now(),
                "last_error": str(exc)[:400], "attempts": c.get("attempts", 0) + 1,
            })
            self.store.save()
        return str(exc)

    def disconnect(self):
        with self._lock:
            if self.connector:
                try:
                    self.connector.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            self.connector = None
            self.store.connection.update({"state": "offline", "last_error": "", "next_retry": ""})
            self.store.save()

    def test(self, cfg):
        """Teste une configuration sans la sauvegarder ni remplacer le connecteur actif."""
        conn = self.build({**self.settings.get("mt5"), **cfg})
        started = time.monotonic()
        info = conn.connect()
        acc = conn.account()
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True, "mode": conn.mode, "latency_ms": int((time.monotonic() - started) * 1000),
            "server": info.get("server", ""), "account": info.get("account", ""),
            "account_info": acc, "message": "Connexion réussie",
        }
