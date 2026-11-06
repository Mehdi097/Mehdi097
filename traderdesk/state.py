"""État temps réel du dashboard : journal, agents, ordres, compte, artefacts."""

import copy
import datetime
import json
import os
import threading
from pathlib import Path

from .settings import APPSTATE_FILE, RUNTIME_DIR


def now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def today():
    return datetime.date.today().isoformat()


class Store:
    def __init__(self, agent_ids):
        self._lock = threading.RLock()
        self.events = []
        self.agents = {
            aid: {
                "status": "idle", "runs": 0, "last_run": None, "duration_ms": 0,
                "summary": "En attente du premier cycle", "output": "", "error": "",
                "enabled": True, "logs": [],
            }
            for aid in agent_ids
        }
        self.orders = []
        self.trades = []
        self.positions = []
        self.account = {}
        self.equity_curve = []
        self.connection = {
            "state": "offline", "mode": "simulation", "address": "", "server": "",
            "account": "", "last_check": None, "last_error": "", "latency_ms": 0,
            "attempts": 0, "next_retry": "",
        }
        self.counters = {"cycles": 0, "signals": 0, "alerts": 0, "blocks": 0, "executions": 0}
        self.artifacts = {}
        self.started_at = now()
        self.load()

    # ---------------------------------------------------------------- persistance
    def load(self):
        try:
            with open(APPSTATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            return
        with self._lock:
            for key in ("events", "orders", "trades", "equity_curve", "counters", "artifacts"):
                if isinstance(data.get(key), type(getattr(self, key))):
                    setattr(self, key, data[key][-600:] if key == "events" else data[key])
            for aid, saved in (data.get("agents") or {}).items():
                if aid in self.agents:
                    self.agents[aid].update(saved)
                    self.agents[aid]["status"] = "idle"
            self.started_at = data.get("started_at", self.started_at)

    def save(self):
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = {
                "events": self.events[-600:], "orders": self.orders[-200:],
                "trades": self.trades[-200:], "equity_curve": self.equity_curve[-300:],
                "counters": self.counters, "agents": self.agents,
                "artifacts": self.artifacts, "started_at": self.started_at,
            }
        tmp = str(APPSTATE_FILE) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, APPSTATE_FILE)
        except OSError:
            pass

    # ---------------------------------------------------------------- journal
    def log(self, message, level="info", agent="system", detail=""):
        with self._lock:
            rec = {
                "id": len(self.events) + 1, "ts": now(), "level": level,
                "agent": agent, "message": message, "detail": str(detail or ""),
            }
            self.events.append(rec)
            if len(self.events) > 800:
                self.events = self.events[-600:]
            if agent in self.agents:
                self.agents[agent]["logs"].append(rec)
                if len(self.agents[agent]["logs"]) > 80:
                    self.agents[agent]["logs"] = self.agents[agent]["logs"][-60:]
        self.save()
        return rec

    def set_agent(self, agent_id, **fields):
        with self._lock:
            if agent_id in self.agents:
                self.agents[agent_id].update(fields)
        self.save()

    # ---------------------------------------------------------------- artefacts
    def refresh_artifacts(self, names):
        out = {}
        for name in names:
            # les noms sont relatifs à la racine du projet (ex. trader/orders.json)
            p = RUNTIME_DIR / name
            if not p.exists():
                continue
            try:
                raw = p.read_text(encoding="utf-8")
                try:
                    out[name] = json.loads(raw)
                except ValueError:
                    out[name] = raw[:6000]
            except OSError:
                continue
        with self._lock:
            self.artifacts = out
        self.save()
        return out

    def add_equity(self, value):
        with self._lock:
            self.equity_curve.append({"t": now(), "v": round(float(value), 2)})
            if len(self.equity_curve) > 300:
                self.equity_curve = self.equity_curve[-300:]
        self.save()

    def add_order(self, rec):
        with self._lock:
            self.orders.append(rec)
            if len(self.orders) > 300:
                self.orders = self.orders[-200:]
            if rec.get("status") in ("filled", "placed"):
                self.trades.append(rec)
                if len(self.trades) > 300:
                    self.trades = self.trades[-200:]
        self.save()

    def snapshot(self, settings, extra=None):
        with self._lock:
            data = {
                "server_time": now(), "started_at": self.started_at,
                "events": copy.deepcopy(self.events[-250:]),
                "agents": copy.deepcopy(self.agents),
                "orders": copy.deepcopy(self.orders[-100:]),
                "trades": copy.deepcopy(self.trades[-100:]),
                "positions": copy.deepcopy(self.positions),
                "account": copy.deepcopy(self.account),
                "equity_curve": copy.deepcopy(self.equity_curve[-120:]),
                "connection": copy.deepcopy(self.connection),
                "counters": copy.deepcopy(self.counters),
                "artifacts": copy.deepcopy(self.artifacts),
                "settings": settings.public(),
            }
        if extra:
            data.update(extra)
        return data

    def reset_demo(self):
        with self._lock:
            self.events, self.orders, self.trades, self.equity_curve = [], [], [], []
            self.counters = {"cycles": 0, "signals": 0, "alerts": 0, "blocks": 0, "executions": 0}
            for a in self.agents.values():
                a.update({"status": "idle", "runs": 0, "last_run": None,
                          "summary": "En attente du premier cycle", "output": "",
                          "error": "", "logs": []})
        self.save()
