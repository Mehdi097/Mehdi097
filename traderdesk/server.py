"""Serveur HTTP local de TraderDesk (bibliothèque standard uniquement).

Sert le dashboard et expose l'API JSON utilisée par l'interface. Aucun appel
réseau vers l'extérieur n'est fait par le serveur lui-même : seuls les agents
et le connecteur MT5 en font, selon les réglages.
"""

import csv
import io
import json
import mimetypes
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agents.registry import AGENTS, PIPELINES, ARTIFACTS, skill_markdown
from .settings import WEB_DIR, SKILLS_DIR, TRADER_DIR


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "TraderDesk/1.0"
    engine = None
    store = None
    settings = None

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt, *args):
        # silencieux : le journal applicatif est dans /api/state
        if os.environ.get("TRADERDESK_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, obj)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def _state(self):
        return self.store.snapshot(self.settings, {
            "agents_spec": [
                {k: v for k, v in a.items() if k not in ("skill_md",)} for a in AGENTS
            ],
            "pipelines": PIPELINES,
            "artifact_list": ARTIFACTS,
            "runtime": {"trader_dir": str(TRADER_DIR), "skills_dir": str(SKILLS_DIR)},
            "pipeline_running": bool(self.engine.pipeline_running if self.engine else False),
            "last_pipeline": self.engine.last_pipeline if self.engine else None,
        })

    # ------------------------------------------------------------------ GET
    def do_OPTIONS(self):
        self._send(204, b"")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path).rstrip("/") or "/"
        try:
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path in ("/app.js", "/styles.css", "/favicon.svg"):
                return self._serve_static(path.lstrip("/"))
            if path == "/api/state":
                return self._json(self._state())
            if path == "/api/health":
                return self._json({"ok": True, "version": "1.0.0"})
            if path == "/api/agents":
                return self._json({"agents": AGENTS, "pipelines": PIPELINES, "artifacts": ARTIFACTS})
            if path.startswith("/api/docs/"):
                agent_id = path.rsplit("/", 1)[-1]
                if agent_id == "readme":
                    p = SKILLS_DIR / "README.md"
                    return self._send(200, p.read_text(encoding="utf-8"), "text/plain; charset=utf-8")
                if agent_id in {a["id"] for a in AGENTS}:
                    return self._send(200, skill_markdown(agent_id), "text/plain; charset=utf-8")
                return self._json({"error": "doc inconnue"}, 404)
            if path == "/api/artifact":
                name = urllib.parse.parse_qs(parsed.query).get("name", [""])[0]
                allowed = {a["file"] for a in ARTIFACTS} | {
                    "trader/state/news_items.json", "trader/state/pelosi_trades.json",
                    "trader/state/tickets.json", "trader/state/alerts_fired.json",
                    "trader/state/rebalance.json", "trader/state/budget.json",
                    "trader/state/analyst.json", "trader/state/copycat.json",
                    "trader/portfolio.json", "trader/config.json",
                }
                if name not in allowed:
                    return self._json({"error": "fichier non autorisé"}, 400)
                p = TRADER_DIR.parent / name
                if not p.exists():
                    return self._json({"error": "fichier absent", "name": name}, 404)
                return self._send(200, p.read_text(encoding="utf-8"), "text/plain; charset=utf-8")
            if path == "/api/export/events.csv":
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["id", "ts", "level", "agent", "message", "detail"])
                for e in self.store.events:
                    w.writerow([e["id"], e["ts"], e["level"], e["agent"], e["message"], e["detail"]])
                return self._send(200, buf.getvalue(), "text/csv; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="traderdesk-journal.csv"'})
            return self._json({"error": "route inconnue", "path": path}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)

    def _serve_static(self, name):
        p = WEB_DIR / name
        if not p.exists():
            return self._json({"error": "fichier statique absent : %s" % name}, 404)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith((".js", ".css", ".html", ".svg")):
            ctype += "; charset=utf-8"
        return self._send(200, p.read_bytes(), ctype)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).rstrip("/")
        body = self._body()
        try:
            if path == "/api/settings":
                before = self.settings.get()
                self.settings.update(body)
                after = self.settings.get()
                self.store.log("Paramètres mis à jour (onglet Connexion MT5)", "info", "system")
                changed = (before["mt5"].get("mode") != after["mt5"].get("mode")
                           or before["mt5"].get("address") != after["mt5"].get("address")
                           or any(body.get("mt5", {}).get(k) for k in ("api_key", "password", "account", "server")))
                # Toujours réécrire trader/config.json avec les nouvelles limites,
                # sans effacer le portefeuille, les ordres ni le journal des agents.
                self.engine.enqueue(self.engine.seed, False)
                if changed and after["mt5"].get("auto_connect"):
                    self.engine.enqueue(self.engine.connect)
                return self._json({"ok": True, "settings": self.settings.public()})

            if path == "/api/mt5/test":
                cfg = body.get("mt5", body)
                # les secrets masqués ne sont pas des valeurs : on garde ceux en mémoire
                for k in ("api_key", "password"):
                    if str(cfg.get(k, "")).startswith("•"):
                        cfg[k] = self.settings.secret(k)
                result = self.engine.test_connection(cfg)
                self.store.log("Test de connexion MT5 : %s" %
                               ("OK" if result.get("ok") else result.get("error")),
                               "success" if result.get("ok") else "error", "system")
                return self._json(result)

            if path == "/api/mt5/connect":
                self.engine.enqueue(self.engine.connect)
                self.store.log("Reconnexion demandée depuis le dashboard", "info", "system")
                return self._json({"ok": True, "task": "started",
                                   "message": "Connexion lancée en arrière-plan"})
            if path == "/api/mt5/connect_now":
                return self._json(self.engine.connect())
            if path == "/api/mt5/disconnect":
                self.engine.disconnect()
                return self._json({"ok": True})

            if path.startswith("/api/agents/") and path.endswith("/run"):
                agent_id = path.split("/")[3]
                if agent_id not in {a["id"] for a in AGENTS}:
                    return self._json({"error": "agent inconnu"}, 404)
                self.engine.enqueue(self.engine.run_agent, agent_id, body)
                return self._json({"ok": True, "task": "started", "agent": agent_id})

            if path.startswith("/api/agents/") and path.endswith("/toggle"):
                agent_id = path.split("/")[3]
                if agent_id not in self.store.agents:
                    return self._json({"error": "agent inconnu"}, 404)
                enabled = not self.store.agents[agent_id].get("enabled", True)
                self.store.set_agent(agent_id, enabled=enabled)
                self.store.log("Agent %s %s" % (agent_id, "activé" if enabled else "désactivé"),
                               "info", agent_id)
                return self._json({"ok": True, "enabled": enabled})

            if path == "/api/pipeline/run":
                if self.engine.pipeline_running:
                    return self._json({"ok": False, "error": "cycle déjà en cours"})
                self.engine.enqueue(self.engine.run_pipeline, True)
                return self._json({"ok": True, "task": "started", "message": "Cycle 11 agents lancé"})

            if path.startswith("/api/orders/") and path.endswith("/approve"):
                fp = path.split("/")[3]
                self.engine.enqueue(self.engine.approve_order, fp)
                return self._json({"ok": True, "task": "started"})
            if path.startswith("/api/orders/") and path.endswith("/reject"):
                fp = path.split("/")[3]
                return self._json(self.engine.reject_order(fp))

            if path == "/api/kill":
                cur = self.settings.get("trading").get("kill_switch")
                self.settings.update({"trading": {"kill_switch": not cur}})
                self.store.log("Kill switch %s" % ("ACTIVÉ — exécution gelée" if not cur else "désactivé"),
                               "error" if not cur else "success", "system")
                return self._json({"ok": True, "kill_switch": not cur})

            if path == "/api/demo/reset":
                self.store.reset_demo()
                self.engine.seed(force=True)
                self.engine.tickets = []
                self.engine.enqueue(self.engine.connect)
                self.store.log("Compte démo réinitialisé", "warn", "system")
                return self._json({"ok": True, "message": "Démo réinitialisée"})

            if path == "/api/toggle":
                section, key = body.get("section", "trading"), body.get("key")
                if not key:
                    return self._json({"error": "clé manquante"}, 400)
                cur = self.settings.get(section).get(key)
                self.settings.update({section: {key: not cur}})
                self.store.log("Réglage %s.%s = %s" % (section, key, not cur), "info", "system")
                return self._json({"ok": True, "value": not cur})

            return self._json({"error": "route inconnue", "path": path}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)


def make_handler(settings, store, engine):
    return type("BoundHandler", (ApiHandler,), {
        "settings": settings, "store": store, "engine": engine,
    })


def serve(host="127.0.0.1", port=8770, settings=None, store=None, engine=None):
    handler = make_handler(settings, store, engine)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd
