"""Chemins, configuration persistante et masquage des secrets.

Aucune dépendance externe : tout tient dans la bibliothèque standard, ce qui
permet de compiler l'application en un seul .exe Windows avec PyInstaller.
"""

import copy
import json
import os
import sys
import threading
from pathlib import Path


def _pkg_dir():
    """Dossier des ressources (différent quand l'app est gelée par PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "traderdesk"
    return Path(__file__).resolve().parent


PKG_DIR = _pkg_dir()
APP_ROOT = PKG_DIR.parent
SKILLS_DIR = PKG_DIR / "skills"
WEB_DIR = PKG_DIR / "web"
SEED_DIR = PKG_DIR / "data" / "seed"


def runtime_dir():
    if os.environ.get("TRADERDESK_HOME"):
        return Path(os.environ["TRADERDESK_HOME"])
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "TraderDesk"
    return APP_ROOT / "runtime"


RUNTIME_DIR = runtime_dir()
TRADER_DIR = RUNTIME_DIR / "trader"
STATE_DIR = TRADER_DIR / "state"
SETTINGS_FILE = RUNTIME_DIR / "settings.json"
APPSTATE_FILE = RUNTIME_DIR / "appstate.json"

SECRET_FIELDS = ("api_key", "password")

DEFAULTS = {
    "mt5": {
        "mode": "simulation",           # simulation | rest | local
        "address": "http://127.0.0.1:8765",
        "api_key": "",
        "account": "",
        "password": "",
        "server": "",
        "terminal_path": "",
        "timeout": 8,
        "auto_connect": True,
        "reconnect_seconds": 15,
        "symbol_prefix": "",
        "symbol_suffix": "",
        "symbol_map": {
            "AAPL": "AAPL", "AXP": "AXP", "GOOGL": "GOOGL", "GOOG": "GOOGL",
            "KO": "KO", "BAC": "BAC", "BRK.B": "BRK.B",
        },
        "magic": 240611,
        "deviation": 20,
    },
    "trading": {
        "auto_execute": True,
        "require_approval": False,
        "live_trading": False,
        "kill_switch": False,
        "paper": True,
        "live_data": False,
        "budget": 5000,
        "cycle_seconds": 90,
        "max_orders_per_cycle": 5,
        "max_daily_orders": 10,
        "max_lot": 100.0,
        "default_sl_pct": 3.0,
        "default_tp_pct": 6.0,
    },
    "risk": {
        "budget": 5000,
        "cash_buffer_pct": 10,
        "max_position_pct": 25,
        "max_order_usd": 2000,
        "min_order_usd": 5,
        "max_orders_per_day": 10,
        "fractional": True,
        "broker": "metatrader5",
        "paper": True,
        "blocked": [],
        "allow_options": False,
        "allow_margin": False,
        "allow_short": False,
        "rebalance_band_pct": 5,
        "sec_user_agent": "TraderDesk User traderdesk@example.com",
    },
}


def _deep_merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Configuration lisible/écrivable par l'UI, avec secrets jamais renvoyés en clair."""

    def __init__(self):
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                saved = json.load(fh)
            with self._lock:
                self.data = _deep_merge(DEFAULTS, saved)
        except (FileNotFoundError, ValueError, OSError):
            pass

    def save(self):
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = str(SETTINGS_FILE) + ".tmp"
        with self._lock:
            payload = copy.deepcopy(self.data)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_FILE)
        try:
            os.chmod(SETTINGS_FILE, 0o600)
        except OSError:
            pass

    def get(self, section=None):
        with self._lock:
            return copy.deepcopy(self.data if section is None else self.data[section])

    def update(self, patch):
        """Applique un patch. Un secret vide = on garde l'ancienne valeur."""
        with self._lock:
            for section, values in (patch or {}).items():
                if section not in self.data or not isinstance(values, dict):
                    continue
                for key, value in values.items():
                    if key in SECRET_FIELDS and isinstance(value, str) and (
                        value == "" or value.startswith("•")
                    ):
                        continue
                    self.data[section][key] = value
            # cohérence
            t = self.data["trading"]
            self.data["risk"]["budget"] = float(t.get("budget") or 5000)
            self.data["risk"]["paper"] = bool(t.get("paper", True))
            self.data["risk"]["max_orders_per_day"] = int(t.get("max_daily_orders") or 10)
            payload = copy.deepcopy(self.data)
        self.save()
        return payload

    def public(self):
        """Version sans secrets pour le dashboard."""
        data = self.get()
        for key in SECRET_FIELDS:
            val = data["mt5"].get(key) or ""
            data["mt5"][key] = ("•" * 8 + val[-4:]) if val else ""
            data["mt5"]["has_" + key] = bool(val)
        data["mt5"]["mode_label"] = {
            "simulation": "Simulation (démo)",
            "rest": "Passerelle REST / API Key",
            "local": "Terminal MT5 local",
        }.get(data["mt5"]["mode"], data["mt5"]["mode"])
        return data

    def secret(self, key):
        with self._lock:
            return self.data["mt5"].get(key) or ""
