"""Passerelle REST MetaTrader 5 (à lancer sur le PC Windows où MT5 est installé).

    python -m traderdesk.mt5.bridge --api-key MA_CLE --port 8765
    # ou, depuis le .exe :
    TraderDesk.exe --bridge --api-key MA_CLE

L'application TraderDesk se connecte ensuite à http://127.0.0.1:8765 avec
cette même clé (onglet « Connexion MT5 » → mode « Passerelle REST »).

Contrat de l'API (en-tête ``X-API-Key`` ou ``Authorization: Bearer``) :
    GET  /api/v1/ping         -> {ok, server, account, mode, message}
    GET  /api/v1/account      -> informations de compte
    GET  /api/v1/positions    -> {positions: [...]}
    GET  /api/v1/symbols      -> {symbols: [...]}
    GET  /api/v1/history      -> {orders: [...]}
    POST /api/v1/order        -> {symbol, side, volume, price?, sl?, tp?, comment?, magic?}
    POST /api/v1/close        -> {ticket}

Si le package officiel ``MetaTrader5`` (pip install MetaTrader5) et le terminal
sont présents, les ordres partent réellement sur MT5. Sinon la passerelle
démarre en mode simulation et le dit clairement dans /ping.
"""

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .connector import SimulationConnector, MT5Error


class Bridge:
    def __init__(self, api_key, mt5_login=None, mt5_password=None, mt5_server=None,
                 terminal_path=None, mode="auto"):
        self.api_key = api_key
        self.mode = mode
        self.mt5 = None
        try:
            import MetaTrader5 as mt5  # type: ignore
            if mt5.initialize(path=terminal_path or None):
                if mt5_login and mt5_password and mt5_server:
                    mt5.login(int(mt5_login), password=mt5_password, server=mt5_server)
                if mt5.account_info() is not None:
                    self.mt5 = mt5
        except Exception:  # noqa: BLE001
            self.mt5 = None
        self.demo = SimulationConnector({}, initial_balance=10000.0)
        self.demo.connect()
        self._lock = threading.RLock()

    @property
    def active(self):
        return "mt5" if self.mt5 and self.mode != "simulation" else "simulation"

    def ping(self):
        if self.mt5 and self.active == "mt5":
            i = self.mt5.account_info()
            return {"ok": i is not None, "server": i.server if i else "",
                    "account": str(i.login) if i else "", "mode": "mt5",
                    "message": "Terminal MetaTrader 5 connecté"}
        return {"ok": True, "server": "TraderDesk-Bridge-Demo", "account": "DEMO-001",
                "mode": "simulation",
                "message": "Passerelle OK — mode SIMULATION (package MetaTrader5 ou terminal absent)"}

    def account(self):
        if self.active == "mt5":
            i = self.mt5.account_info()
            return {"login": str(i.login), "server": i.server, "currency": i.currency,
                    "balance": i.balance, "equity": i.equity, "margin": i.margin,
                    "free_margin": i.margin_free, "profit": i.profit, "leverage": i.leverage,
                    "trade_allowed": True, "mode": "mt5"}
        return self.demo.account()

    def positions(self):
        if self.active == "mt5":
            return {"positions": [{
                "ticket": p.ticket, "symbol": p.symbol, "side": "buy" if p.type == 0 else "sell",
                "volume": p.volume, "price_open": p.price_open, "price_current": p.price_current,
                "sl": p.sl, "tp": p.tp, "profit": p.profit, "time": str(p.time),
                "comment": p.comment,
            } for p in (self.mt5.positions_get() or [])]}
        return {"positions": self.demo.positions()}

    def symbols(self):
        if self.active == "mt5":
            return {"symbols": [{"symbol": s.name, "bid": s.bid, "ask": s.ask,
                                 "volume_min": s.volume_min, "volume_step": s.volume_step}
                                for s in (self.mt5.symbols_get() or [])[:300]]}
        return {"symbols": self.demo.symbols()}

    def order(self, payload):
        symbol = payload.get("symbol")
        side = payload.get("side")
        volume = float(payload.get("volume") or 0)
        if not symbol or side not in ("buy", "sell") or volume <= 0:
            raise MT5Error("payload invalide : symbol, side et volume > 0 requis")
        if self.active == "mt5":
            mt5 = self.mt5
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise MT5Error("symbole %s introuvable dans MT5" % symbol)
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
                "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
                "price": tick.ask if side == "buy" else tick.bid,
                "deviation": int(payload.get("deviation") or 20),
                "magic": int(payload.get("magic") or 240611),
                "comment": str(payload.get("comment") or "TraderDesk")[:30],
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
            }
            for key in ("sl", "tp"):
                if payload.get(key):
                    req[key] = float(payload[key])
            r = mt5.order_send(req)
            if r is None:
                raise MT5Error("order_send : %s" % mt5.last_error())
            if r.retcode not in (mt5.TRADE_RETCODE_DONE, 10008, 10009):
                raise MT5Error("MT5 retcode %s : %s" % (r.retcode, r.comment))
            return {"ok": True, "ticket": r.order, "retcode": r.retcode, "price": r.price,
                    "status": "placed", "symbol": symbol, "side": side, "volume": volume,
                    "mode": "mt5", "comment": r.comment}
        return {"ok": True, **self.demo.place_order(
            symbol=symbol, side=side, volume=volume, price=payload.get("price"),
            sl=payload.get("sl"), tp=payload.get("tp"), comment=payload.get("comment"),
            magic=payload.get("magic"))}

    def close(self, payload):
        ticket = payload.get("ticket")
        if self.active == "mt5":
            mt5 = self.mt5
            pos = next((p for p in (mt5.positions_get() or []) if p.ticket == int(ticket)), None)
            if not pos:
                raise MT5Error("position %s introuvable" % ticket)
            t = mt5.symbol_info_tick(pos.symbol)
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
                   "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                   "price": t.bid if pos.type == 0 else t.ask, "position": pos.ticket,
                   "deviation": 20, "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": mt5.ORDER_FILLING_IOC, "comment": "TraderDesk close"}
            r = mt5.order_send(req)
            return {"ok": r is not None, "ticket": ticket, "status": "closed" if r else "failed"}
        return {"ok": True, **self.demo.close_position(ticket)}

    def history(self):
        return {"orders": self.demo.history() if self.active == "simulation" else []}


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TraderDeskBridge/1.0"

        def log_message(self, fmt, *args):
            print("[bridge] " + (fmt % args), flush=True)

        def _auth(self):
            key = self.headers.get("X-API-Key") or ""
            if not key:
                auth = self.headers.get("Authorization") or ""
                key = auth[7:] if auth.lower().startswith("bearer ") else ""
            return bridge.api_key and key == bridge.api_key

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/":
                return self._send(200, {"service": "TraderDesk MT5 bridge",
                                       "docs": "/api/v1/ping", "mode": bridge.active})
            if not self._auth():
                return self._send(401, {"ok": False, "error": "clé API invalide (X-API-Key)"})
            payload = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    try:
                        payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    except ValueError:
                        return self._send(400, {"ok": False, "error": "JSON invalide"})
            try:
                with bridge._lock:
                    if method == "GET" and path == "/api/v1/ping":
                        return self._send(200, bridge.ping())
                    if method == "GET" and path == "/api/v1/account":
                        return self._send(200, bridge.account())
                    if method == "GET" and path == "/api/v1/positions":
                        return self._send(200, bridge.positions())
                    if method == "GET" and path == "/api/v1/symbols":
                        return self._send(200, bridge.symbols())
                    if method == "GET" and path == "/api/v1/history":
                        return self._send(200, bridge.history())
                    if method == "POST" and path == "/api/v1/order":
                        return self._send(200, bridge.order(payload))
                    if method == "POST" and path == "/api/v1/close":
                        return self._send(200, bridge.close(payload))
                return self._send(404, {"ok": False, "error": "endpoint inconnu : " + path})
            except Exception as e:  # noqa: BLE001
                return self._send(200, {"ok": False, "error": str(e), "status": "rejected"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_OPTIONS(self):
            self._send(200, {"ok": True})

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Passerelle REST MetaTrader 5 pour TraderDesk")
    ap.add_argument("--api-key", default=os.environ.get("TRADERDESK_API_KEY", "change-moi"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--login", default=os.environ.get("MT5_LOGIN", ""))
    ap.add_argument("--password", default=os.environ.get("MT5_PASSWORD", ""))
    ap.add_argument("--server", default=os.environ.get("MT5_SERVER", ""))
    ap.add_argument("--terminal-path", default=os.environ.get("MT5_PATH", ""))
    ap.add_argument("--mode", choices=["auto", "simulation"], default="auto")
    a = ap.parse_args(argv)
    bridge = Bridge(a.api_key, a.login, a.password, a.server, a.terminal_path, a.mode)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(bridge))
    print("Passerelle TraderDesk MT5 sur http://%s:%d  |  mode: %s  |  clé: %s" %
          (a.host, a.port, bridge.active, a.api_key[:3] + "•••"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
