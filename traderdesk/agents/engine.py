"""Moteur d'orchestration des 11 agents + boucle de connexion / exécution MT5.

Les scripts Python du dépôt trader-skill sont exécutés tels quels (ils lisent
et écrivent le dossier ``trader/``), puis TraderDesk ajoute la couche
MetaTrader 5 : conversion de l'ordre approuvé en volume MT5, envoi au
connecteur, enregistrement du ticket et du fill (lots fiscaux).
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from .. import settings as cfgmod
from ..mt5 import MT5Error
from .registry import AGENTS, AGENTS_BY_ID, ARTIFACTS

ARTIFACT_NAMES = [a["file"] for a in ARTIFACTS] + [
    "trader/state/news_items.json", "trader/state/pelosi_trades.json",
    "trader/state/tickets.json", "trader/state/alerts_fired.json",
    "trader/state/rebalance.json", "trader/state/budget.json",
    "trader/state/analyst.json", "trader/state/copycat.json",
]

DEMO_NEWS = [
    {"ticker": "AAPL", "title": "Apple files 8-K (Item 2.02) with Q3 results and EX-99.1 press release",
     "source": "SEC EDGAR", "tag": "earnings", "important": True, "date": "2026-07-30",
     "link": "https://www.sec.gov/Archives/edgar/data/320193/"},
    {"ticker": "AAPL", "title": "Apple services revenue keeps growing, analysts watch margins",
     "source": "Yahoo Finance RSS", "tag": "analyst", "important": False, "date": "2026-10-13",
     "link": "https://finance.yahoo.com/"},
    {"ticker": "BAC", "title": "Bank of America 10-Q: net interest income and credit quality in focus",
     "source": "SEC EDGAR", "tag": "earnings", "important": False, "date": "2026-10-12",
     "link": "https://www.sec.gov/Archives/edgar/data/70858/"},
    {"ticker": "KO", "title": "Coca-Cola names new CFO in 8-K Item 5.02",
     "source": "SEC EDGAR", "tag": "people", "important": True, "date": "2026-10-11",
     "link": "https://www.sec.gov/Archives/edgar/data/21344/"},
    {"ticker": "GOOGL", "title": "Alphabet: cloud segment and AI capex discussed in latest filing",
     "source": "Yahoo Finance RSS", "tag": "risk", "important": False, "date": "2026-10-10",
     "link": "https://finance.yahoo.com/"},
]

DEMO_PTRS = [
    {"member": "Nancy Pelosi", "owner": "SP", "ticker": "NVDA", "side": "buy",
     "amount": "$1,000,001 - $5,000,000", "trade_date": "2026-09-24", "filed": "2026-10-06",
     "days_to_disclose": 12, "doc_id": "20035590", "held_by_you": False},
    {"member": "Nancy Pelosi", "owner": "SP", "ticker": "AAPL", "side": "sell",
     "amount": "$250,001 - $500,000", "trade_date": "2026-09-18", "filed": "2026-10-06",
     "days_to_disclose": 18, "doc_id": "20035562", "held_by_you": True},
    {"member": "Josh Gottheimer", "owner": "", "ticker": "BAC", "side": "buy",
     "amount": "$1,001 - $15,000", "trade_date": "2026-09-30", "filed": "2026-10-14",
     "days_to_disclose": 14, "doc_id": "20033725", "held_by_you": True},
]


def now():
    return datetime.now().replace(microsecond=0).isoformat()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, p)


class Engine:
    def __init__(self, settings, store, connectors):
        self.settings = settings
        self.store = store
        self.connectors = connectors
        self.skills = cfgmod.SKILLS_DIR
        self.trader = cfgmod.TRADER_DIR
        # Les scripts du pack attendent un dossier de projet contenant trader/ :
        # c'est RUNTIME_DIR qui sert de cwd, pas TRADER_DIR.
        self.work = cfgmod.RUNTIME_DIR
        self.seed_dir = cfgmod.SEED_DIR
        self.state_dir = cfgmod.STATE_DIR
        self._run_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._modules = {}
        self.tickets = []
        self.last_pipeline = None
        self.pipeline_running = False

    # ------------------------------------------------------------------ démarrage
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="traderdesk-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def enqueue(self, fn, *args):
        t = threading.Thread(target=self._safe(fn, *args), daemon=True)
        t.start()
        return t

    def _safe(self, fn, *args):
        def wrapper():
            try:
                return fn(*args)
            except Exception as e:  # noqa: BLE001
                self.store.log("Erreur inattendue : %s" % e, "error", "system", repr(e))
        return wrapper

    def seed(self, force=False):
        """Prépare le dossier trader/ avec les données d'exemple du dépôt."""
        self.trader.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        risk = self.settings.get("risk")
        trading = self.settings.get("trading")
        config = copy.deepcopy(risk)
        config["budget"] = float(trading.get("budget") or 5000)
        config["paper"] = bool(trading.get("paper", True))
        config["max_orders_per_day"] = int(trading.get("max_daily_orders") or 10)
        write_json(self.trader / "config.json", config)
        mapping = {
            "targets.json": "targets.json", "metrics.json": "metrics.json",
            "rules.json": "rules.json", "alerts.json": "alerts.json",
            "prices.json": "prices.json",
        }
        for dest, src in mapping.items():
            p = self.trader / dest
            if force or not p.exists():
                seed = read_json(self.seed_dir / src)
                if seed is not None:
                    write_json(p, seed)
        pf = self.trader / "portfolio.json"
        if force or not pf.exists():
            write_json(pf, {"cash": float(config["budget"]), "positions": []})
        for name in ("broker.json", "risk.json", "tax.json", "alerts.json", "news.json", "pelosi.json"):
            p = self.state_dir / name
            if force and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        if force:
            # remet aussi le compte démo MT5 à zéro
            for name in ("mt5_simulation.json", "mt5_bridge_simulation.json"):
                p = cfgmod.RUNTIME_DIR / name
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
        self.store.refresh_artifacts(ARTIFACT_NAMES)

    # ------------------------------------------------------------------ outils
    def _run_tool(self, tool, args, timeout=25):
        script = Path(self.skills) / tool
        if not script.exists():
            return 127, "", "script introuvable : %s" % script
        args = [str(a) for a in args]
        if getattr(sys, "frozen", False):
            return self._run_inprocess(script, args)
        env = os.environ.copy()
        env["SEC_USER_AGENT"] = str(self.settings.get("risk").get("sec_user_agent") or "TraderDesk User")
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            p = subprocess.run([sys.executable, str(script), *args],
                               cwd=str(self.work), env=env, capture_output=True,
                               text=True, timeout=timeout)
            return p.returncode, p.stdout or "", p.stderr or ""
        except subprocess.TimeoutExpired:
            return 124, "", "délai dépassé (%ss)" % timeout
        except OSError as e:
            return 127, "", str(e)

    def _run_inprocess(self, script, args):
        """Mode .exe gelé : pas de python.exe séparé, on importe le script."""
        key = str(script)
        with self._run_lock:
            mod = self._modules.get(key)
            if mod is None:
                name = "td_skill_" + hashlib.md5(key.encode()).hexdigest()[:10]
                spec = importlib.util.spec_from_file_location(name, str(script))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._modules[key] = mod
            old_cwd = os.getcwd()
            old_argv = sys.argv
            old_ua = os.environ.get("SEC_USER_AGENT")
            out, err = io.StringIO(), io.StringIO()
            os.environ["SEC_USER_AGENT"] = str(self.settings.get("risk").get("sec_user_agent") or "TraderDesk User")
            try:
                os.chdir(self.work)
                sys.argv = [str(script), *args]
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = mod.main(list(args))
                return int(rc or 0), out.getvalue(), err.getvalue()
            except SystemExit as e:
                return int(e.code or 0), out.getvalue(), err.getvalue()
            except Exception as e:  # noqa: BLE001
                return 1, out.getvalue(), "%s: %s" % (type(e).__name__, e)
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
                if old_ua is None:
                    os.environ.pop("SEC_USER_AGENT", None)
                else:
                    os.environ["SEC_USER_AGENT"] = old_ua

    def _tool(self, agent_id, args, timeout=25):
        tool = AGENTS_BY_ID[agent_id]["tool"]
        return self._run_tool(tool, args, timeout)

    # ------------------------------------------------------------------ connexion
    def connect(self, cfg=None):
        try:
            info = self.connectors.connect(cfg)
            self.store.log("Connecté à %s — %s (compte %s)" %
                           (info.get("server", "?"), info.get("message", ""), info.get("account", "?")),
                           "success", "system")
            self._refresh_account()
            return {"ok": True, **info}
        except Exception as e:  # noqa: BLE001
            self.connectors.fail(e, cfg)
            self.store.log("Connexion MT5 échouée : %s" % e, "error", "system")
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self.connectors.disconnect()
        self.store.log("Connexion MT5 fermée", "warn", "system")

    def test_connection(self, cfg):
        try:
            return self.connectors.test(cfg)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def _refresh_account(self):
        conn = self.connectors.current
        if not conn or not conn.connected:
            return
        try:
            acc = conn.account()
            positions = conn.positions()
            with self._run_lock:
                self.store.account = acc
                self.store.positions = positions
                self.store.connection["state"] = "connected"
                self.store.connection["last_check"] = now()
                self.store.connection["last_error"] = ""
            self.store.add_equity(acc.get("equity", 0))
            # met à jour prices.json pour les autres agents (budget/risk/tax)
            if conn.mode == "simulation":
                prices = read_json(self.trader / "prices.json", {}) or {}
                prices.setdefault("prices", {}).update(
                    {p["symbol"]: p["price_current"] for p in positions} or conn.prices
                )
                prices["as_of"] = date.today().isoformat()
                prices["source"] = "TraderDesk simulation (cotations différées)"
                write_json(self.trader / "prices.json", prices)
        except Exception as e:  # noqa: BLE001
            self.store.log("Lecture du compte MT5 : %s" % e, "warn", "system")

    # ------------------------------------------------------------------ agents
    def run_agent(self, agent_id, params=None):
        if agent_id not in AGENTS_BY_ID:
            return {"ok": False, "error": "agent inconnu"}
        with self._run_lock:
            self.store.set_agent(agent_id, status="running")
            self.store.log("Démarrage de %s" % AGENTS_BY_ID[agent_id]["command"], "info", agent_id)
            started = time.monotonic()
            try:
                fn = getattr(self, "_agent_" + agent_id.replace("trader-", "").replace("-", "_"))
                result = fn(params or {})
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "summary": "Erreur : %s" % e, "output": repr(e)}
                self.store.log("%s : %s" % (agent_id, e), "error", agent_id)
            duration = int((time.monotonic() - started) * 1000)
            st = self.store.agents[agent_id]
            self.store.set_agent(agent_id, status="ok" if result.get("ok", True) else "error",
                                 runs=st["runs"] + 1, last_run=now(), duration_ms=duration,
                                 summary=result.get("summary", ""),
                                 output=(result.get("output") or "")[:6000],
                                 error="" if result.get("ok", True) else result.get("summary", ""))
            self.store.log("%s — %s" % (AGENTS_BY_ID[agent_id]["role"], result.get("summary", "")),
                           "success" if result.get("ok", True) else "error", agent_id)
            self.store.refresh_artifacts(ARTIFACT_NAMES)
            self.store.save()
            return {"ok": result.get("ok", True), "summary": result.get("summary", ""),
                    "duration_ms": duration}

    # 1. copycat --------------------------------------------------------------
    def _agent_copycat(self, params):
        live = self.settings.get("trading").get("live_data")
        source = "SEC EDGAR en direct"
        if live:
            rc, out, err = self._tool("trader-copycat", ["copy", "1067983", "--top", "5",
                                                        "--out", "trader/targets.json"], 40)
            if rc != 0 or not (self.trader / "targets.json").exists():
                self.store.log("SEC injoignable, repli sur le 13F d'exemple : %s" % (err or out)[:180],
                               "warn", "trader-copycat")
                source = "13F d'exemple (hors ligne)"
                write_json(self.trader / "targets.json", read_json(self.seed_dir / "targets.json"))
        else:
            source = "13F d'exemple (mode démo, données publiques du dépôt)"
            write_json(self.trader / "targets.json", read_json(self.seed_dir / "targets.json"))
        doc = read_json(self.trader / "targets.json", {}) or {}
        rows = doc.get("weights", [])
        write_json(self.state_dir / "copycat.json", {
            "agent": "trader-copycat", "source": source, "as_of": doc.get("as_of"),
            "filed": doc.get("filed"), "cik": doc.get("cik"),
            "positions": rows, "checked_at": now(),
        })
        self.store.counters["signals"] += len(rows)
        top = ", ".join("%s %.2f%%" % (r["ticker"], r["weight"]) for r in rows[:3])
        return {"ok": True,
                "summary": "%d positions reconstruites · %s · source : %s" % (len(rows), top, source),
                "output": json.dumps(doc, indent=2, ensure_ascii=False)[:4000]}

    # 2. news -----------------------------------------------------------------
    def _agent_news(self, params):
        live = self.settings.get("trading").get("live_data")
        items = DEMO_NEWS
        source = "flux d'exemple (mode démo)"
        if live:
            rc, out, err = self._tool("trader-news", ["--tickers", "AAPL", "AXP", "GOOGL", "KO", "BAC",
                                                     "--hours", "24", "--json"], 30)
            try:
                parsed = json.loads(out)
                if isinstance(parsed, dict):
                    items = parsed.get("items", parsed.get("news", DEMO_NEWS))
                elif isinstance(parsed, list):
                    items = parsed
                source = "Yahoo RSS + SEC EDGAR en direct"
            except ValueError:
                self.store.log("Flux d'actualité indisponible, repli démo : %s" % (err or out)[:160],
                               "warn", "trader-news")
        tickers = sorted({i.get("ticker", "?") for i in items})
        imp = [i for i in items if i.get("important")]
        held = read_json(self.trader / "portfolio.json", {}) or {}
        for i in items:
            i["held_by_you"] = any(p.get("ticker") == i.get("ticker") for p in held.get("positions", []))
        write_json(self.state_dir / "news_items.json", {"as_of": now(), "source": source, "items": items})
        self.store.counters["signals"] += len(items)
        for i in imp:
            self.store.log("8-K important %s : %s" % (i["ticker"], i["title"]), "warn", "trader-news")
        return {"ok": True,
                "summary": "%d items sur %s · %d dépôts/faits marquants !" % (len(items), ", ".join(tickers), len(imp)),
                "output": json.dumps(items, indent=2, ensure_ascii=False)[:4000]}

    # 3. pelosi ---------------------------------------------------------------
    def _agent_pelosi(self, params):
        live = self.settings.get("trading").get("live_data")
        rows = copy.deepcopy(DEMO_PTRS)
        source = "House Clerk, jeu d'exemple (mode démo)"
        if live:
            rc, out, err = self._tool("trader-pelosi", ["index", "--member", "pelosi"], 30)
            if rc == 0 and out.strip():
                source = "House Clerk en direct"
                self.store.log("Index PTR récupéré (%d lignes)" % len(out.splitlines()),
                               "info", "trader-pelosi")
            else:
                self.store.log("House Clerk injoignable, repli démo : %s" % (err or out)[:160],
                               "warn", "trader-pelosi")
        held = read_json(self.trader / "portfolio.json", {}) or {}
        held_tickers = {p.get("ticker") for p in held.get("positions", [])}
        for r in rows:
            r["held_by_you"] = r["ticker"] in held_tickers
        write_json(self.state_dir / "pelosi_trades.json", {"as_of": now(), "source": source, "trades": rows})
        self.store.counters["signals"] += len(rows)
        matched = [r["ticker"] for r in rows if r["held_by_you"]]
        return {"ok": True,
                "summary": "%d déclarations PTR lues · %d titres en commun avec votre portefeuille%s" %
                           (len(rows), len(matched), " (" + ", ".join(matched) + ")" if matched else ""),
                "output": json.dumps(rows, indent=2, ensure_ascii=False)[:4000]}

    # 4. analyst --------------------------------------------------------------
    def _agent_analyst(self, params):
        live = self.settings.get("trading").get("live_data")
        source = "SEC XBRL, jeu d'exemple du dépôt (mode démo)"
        if live:
            rc, out, err = self._tool("trader-analyst", ["AAPL", "AXP", "GOOGL", "KO", "BAC",
                                                        "--metrics", "trader/metrics.json"], 40)
            if rc == 0 and (self.trader / "metrics.json").exists():
                source = "SEC EDGAR XBRL en direct"
            else:
                self.store.log("SEC XBRL indisponible, repli démo : %s" % (err or out)[:160],
                               "warn", "trader-analyst")
                write_json(self.trader / "metrics.json", read_json(self.seed_dir / "metrics.json"))
        else:
            write_json(self.trader / "metrics.json", read_json(self.seed_dir / "metrics.json"))
        doc = read_json(self.trader / "metrics.json", {}) or {}
        companies = doc.get("companies", [])
        write_json(self.state_dir / "analyst.json", {"as_of": now(), "source": source,
                                                    "companies": companies})
        a = next((c for c in companies if c["ticker"] == "AAPL"), {})
        return {"ok": True,
                "summary": "%d sociétés analysées · AAPL revenue TTM %s Md$, croissance %s%% · %s" %
                           (len(companies), round(a.get("revenue_ttm", 0) / 1e9, 1),
                            a.get("revenue_growth_yoy"), source),
                "output": json.dumps(doc, indent=2, ensure_ascii=False)[:4000]}

    # 5. screener -------------------------------------------------------------
    def _agent_screener(self, params):
        rc, out, err = self._tool("trader-screener", [
            "trader/metrics.json", "--rules", "trader/rules.json",
            "--prices", "trader/prices.json", "--out", "trader/shortlist.json", "--json"])
        try:
            doc = json.loads(out)
        except ValueError:
            doc = read_json(self.trader / "shortlist.json", {}) or {}
        passed = doc.get("passed", [])
        failed = doc.get("failed", [])
        winners = ", ".join("%s (%.2f)" % (p["ticker"], p.get("score") or 0) for p in passed[:3])
        return {"ok": True,
                "summary": "%d/%d sociétés passent les règles%s · %d recalées" %
                           (len(passed), len(passed) + len(failed),
                            " : " + winners if winners else "", len(failed)),
                "output": json.dumps(doc, indent=2, ensure_ascii=False)[:4000]}

    # 6. budget ---------------------------------------------------------------
    def _agent_budget(self, params):
        budget = float(self.settings.get("trading").get("budget") or 5000)
        rc, out, err = self._tool("trader-budget", ["--budget", str(budget), "--write", "--json"])
        try:
            doc = json.loads(out)
        except ValueError:
            doc = {}
        orders = doc.get("orders", read_json(self.trader / "orders.json", []))
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        result = doc.get("result", {})
        write_json(self.state_dir / "budget.json", {"as_of": now(), "result": result,
                                                   "orders": orders})
        total = sum(float(o.get("notional") or 0) for o in orders)
        cash = round(budget - total, 2)
        return {"ok": rc == 0,
                "summary": "%d ordres proposés · %.2f $ investis · %.2f $ de cash buffer · plafond %.0f%%" %
                           (len(orders), total, cash,
                            self.settings.get("risk").get("max_position_pct", 25)),
                "output": json.dumps(doc, indent=2, ensure_ascii=False)[:4000] or err}

    # 7. risk -----------------------------------------------------------------
    def _agent_risk(self, params):
        rc, out, err = self._tool("trader-risk", ["--json"])
        try:
            doc = json.loads(out)
        except ValueError:
            doc = read_json(self.state_dir / "risk.json", {}) or {}
        passed = doc.get("pass", 0)
        blocked = doc.get("block", 0)
        self.store.counters["blocks"] += blocked
        reasons = []
        for r in doc.get("results", []):
            if r.get("verdict") == "BLOCK":
                reasons.append("%s %s : %s" % (r.get("side"), r.get("symbol"),
                                               "; ".join(r.get("reasons", []))[:110]))
                self.store.log("BLOCK %s %s — %s" % (r.get("side"), r.get("symbol"),
                                                     "; ".join(r.get("reasons", []))[:160]),
                               "warn", "trader-risk")
        for w in doc.get("warnings", [])[:5]:
            self.store.log("Avertissement risque : %s" % w, "warn", "trader-risk")
        return {"ok": True,
                "summary": "%d PASS / %d BLOCK · cash après ordres : %s $%s" %
                           (passed, blocked, doc.get("cash_after", "?"),
                            " · " + reasons[0] if reasons else ""),
                "output": json.dumps(doc, indent=2, ensure_ascii=False)[:4000] or err}

    # 8. broker ---------------------------------------------------------------
    def refresh_tickets(self):
        """Relit ticket.py show --json après des décisions, pour refléter DONE/APPROVED."""
        rc, out, err = self._tool("trader-broker", ["show", "--json"])
        try:
            tickets = json.loads(out)
        except ValueError:
            tickets = self.tickets
        if isinstance(tickets, dict):
            tickets = [tickets]
        if tickets:
            self.tickets = tickets
            write_json(self.state_dir / "tickets.json", {"as_of": now(), "tickets": tickets})
        return self.tickets

    def _agent_broker(self, params):
        self.tickets = []
        tickets = self.refresh_tickets()
        ready = [t for t in tickets if t.get("ready")]
        self.store.log("%d ticket(s) READY sur %d (fingerprint risque du jour)" %
                       (len(ready), len(tickets)), "info", "trader-broker")
        return {"ok": True,
                "summary": "%d tickets générés · %d READY · %d déjà décidés/bloqués" %
                           (len(tickets), len(ready), len(tickets) - len(ready)),
                "output": json.dumps(tickets, indent=2, ensure_ascii=False)[:6000]}

    # 9. tax ------------------------------------------------------------------
    def _agent_tax(self, params):
        rc, out, err = self._tool("trader-tax", ["report", "--lots"])
        text = out or err
        rc2, out2, err2 = self._tool("trader-tax", ["harvest", "--min-loss", "100"])
        pf = read_json(self.trader / "portfolio.json", {}) or {}
        lots = sum(len(p.get("lots", [])) for p in pf.get("positions", []))
        return {"ok": True,
                "summary": "%d position(s), %d lot(s) fiscal(aux) · harvest : %s" %
                           (len(pf.get("positions", [])), lots,
                            (out2 or err2).strip().splitlines()[0][:110] if (out2 or err2).strip() else "aucun candidat"),
                "output": (text + "\n\n--- harvest ---\n" + (out2 or err2))[:6000]}

    # 10. alerts --------------------------------------------------------------
    def _agent_alerts(self, params):
        rc_clock, clock, err_clock = self._tool("trader-alerts", ["clock"])
        rc_list, listed, err_list = self._tool("trader-alerts", ["list"])
        rules = (read_json(self.trader / "alerts.json", {}) or {}).get("rules", [])
        prices = (read_json(self.trader / "prices.json", {}) or {}).get("prices", {})
        fired_state = read_json(self.state_dir / "alerts_fired.json", {}) or {}
        fired = fired_state.get("fired", [])
        new_fired = []
        today_str = date.today().isoformat()
        for r in rules:
            rid = r.get("id") or "%s-%s-%s" % (r.get("symbol", "bell"), r.get("type"), r.get("price", ""))
            price = prices.get(r.get("symbol"))
            hit = False
            typ = r.get("type")
            market_open = "closed" not in (clock or "").lower() and "closed" not in (err_clock or "").lower()
            if typ == "opening_bell":
                hit = market_open and (rid + today_str) not in fired
            elif price is not None:
                if typ == "above" and price >= float(r.get("price", 0)):
                    hit = True
                elif typ in ("below", "stop") and price <= float(r.get("price", 0)):
                    hit = True
            if hit:
                new_fired.append({"id": rid, "at": now(), "type": typ,
                                  "symbol": r.get("symbol", "NYSE"),
                                  "price": price, "message": "%s %s a sonné (prix %s)" %
                                  (r.get("symbol", "Cloche NYSE"), typ, price)})
                fired.append(rid + today_str)
                self.store.log("ALERTE %s %s — prix %s" % (r.get("symbol", "NYSE"), typ, price),
                               "warn", "trader-alerts")
        self.store.counters["alerts"] += len(new_fired)
        write_json(self.state_dir / "alerts_fired.json", {"as_of": now(), "fired": fired[-200:],
                                                         "last": new_fired})
        live = self.settings.get("trading").get("live_data")
        if live:
            self._tool("trader-alerts", ["check"], 35)
            self._tool("trader-alerts", ["quote", "--holdings", "--write"], 35)
        market = "fermé" if "closed" in (clock or "").lower() else "ouvert"
        return {"ok": True,
                "summary": "%d règles actives · marché NYSE %s · %d alerte(s) déclenchée(s) · cotations %s" %
                           (len(rules), market, len(new_fired), "direct" if live else "démo"),
                "output": ((clock or err_clock) + "\n\n--- règles ---\n" + (listed or err_list))[:6000]}

    # 11. rebalance -----------------------------------------------------------
    def _agent_rebalance(self, params):
        band = self.settings.get("risk").get("rebalance_band_pct", 5)
        rc, out, err = self._tool("trader-rebalance", ["--band", str(band), "--json"])
        text = out or err
        try:
            doc = json.loads(out)
            trades = doc.get("trades", doc.get("orders", []))
        except ValueError:
            trades = []
        write_json(self.state_dir / "rebalance.json", {"as_of": now(), "band": band,
                                                      "trades": trades, "report": text[:4000]})
        return {"ok": True,
                "summary": "%d trade(s) hors bande de %s points%s" %
                           (len(trades), band, " · portefeuille aligné sur les cibles" if not trades else ""),
                "output": text[:6000]}

    # ------------------------------------------------------------------ pipeline
    def run_pipeline(self, manual=False):
        with self._run_lock:
            if self.pipeline_running:
                return {"ok": False, "error": "un cycle est déjà en cours"}
            self.pipeline_running = True
        self.store.counters["cycles"] += 1
        n = self.store.counters["cycles"]
        self.store.log("=== CYCLE %d — pipeline 11 agents ===" % n, "info", "system")
        order = [
            "trader-alerts", "trader-copycat", "trader-news", "trader-pelosi",
            "trader-analyst", "trader-screener", "trader-budget", "trader-risk",
            "trader-broker", "trader-tax", "trader-rebalance",
        ]
        results = {}
        try:
            for aid in order:
                if not self.store.agents[aid].get("enabled", True):
                    self.store.log("%s désactivé, étape ignorée" % aid, "warn", aid)
                    continue
                results[aid] = self.run_agent(aid)
            exe = self.execute_orders()
            if exe.get("executed"):
                self._post_execution_refresh()
            else:
                self.store.refresh_artifacts(ARTIFACT_NAMES)
            self.store.log("Cycle %d terminé — %d ordre(s) envoyé(s) à MT5" %
                           (n, exe.get("executed", 0)), "success", "system")
            self.last_pipeline = now()
            self.store.save()
            return {"ok": True, "cycle": n, "agents": results, "execution": exe}
        finally:
            self.pipeline_running = False

    # ------------------------------------------------------------------ exécution MT5
    def _price_for(self, symbol):
        prices = (read_json(self.trader / "prices.json", {}) or {}).get("prices", {})
        if symbol in prices:
            return float(prices[symbol])
        conn = self.connectors.current
        if conn and hasattr(conn, "quote"):
            return float(conn.quote(symbol))
        return 100.0

    def _map_symbol(self, symbol):
        mt5 = self.settings.get("mt5")
        custom = (mt5.get("symbol_map") or {}).get(symbol.upper())
        if custom:
            return custom
        return "%s%s%s" % (mt5.get("symbol_prefix", ""), symbol.upper(), mt5.get("symbol_suffix", ""))

    def _executed_fingerprints(self):
        return {o.get("fingerprint") for o in self.store.orders if o.get("status") in ("filled", "placed")}

    def _gates(self, verbose=True):
        t = self.settings.get("trading")
        conn = self.connectors.current
        if t.get("kill_switch"):
            return "Kill switch activé — aucune exécution autorisée"
        if not t.get("auto_execute") and verbose:
            return None  # géré par _pending
        if not conn or not conn.connected:
            return "MT5 non connecté"
        if conn.mode != "simulation" and not t.get("live_trading"):
            return "Mode réel détecté : cochez « Autoriser le trading réel » pour envoyer des ordres"
        return None

    def _execute_ticket(self, ticket, force=False):
        """Un ordre = un ticket approuvé = un ordre MT5 = un fill enregistré."""
        t = self.settings.get("trading")
        conn = self.connectors.current
        idx = ticket.get("index")
        fp = ticket.get("fingerprint")
        oi = ticket.get("tool_input", {}) or {}
        symbol = (oi.get("symbol") or ticket.get("plain", "")).upper()
        side = str(oi.get("side") or "buy").lower()
        notional = float(oi.get("notional") or 0)
        price = self._price_for(symbol)
        if notional <= 0 and oi.get("qty"):
            notional = float(oi["qty"]) * price
        volume = round(max(0.01, notional / max(price, 0.01)), 2)
        max_lot = float(t.get("max_lot") or 100)
        if volume > max_lot:
            volume = max_lot
        if not force:
            gate = self._gates()
            if gate:
                return {"ok": False, "skipped": True, "reason": gate}
        if fp in self._executed_fingerprints():
            return {"ok": False, "skipped": True, "reason": "déjà exécuté"}
        daily = sum(1 for o in self.store.orders
                    if o.get("status") in ("filled", "placed") and str(o.get("time", "")).startswith(date.today().isoformat()))
        if daily >= int(t.get("max_daily_orders") or 10):
            return {"ok": False, "skipped": True, "reason": "plafond journalier atteint"}
        # 1) le « yes » explicite pour CET ordre, enregistré mot pour mot par ticket.py
        rc, out, err = self._tool("trader-broker", ["approve", "--index", idx, "--reply", "yes"])
        if rc != 0:
            return {"ok": False, "reason": "ticket.py a refusé le oui : %s" % (err or out).strip()[:180]}
        sl_pct = float(t.get("default_sl_pct") or 0) / 100
        tp_pct = float(t.get("default_tp_pct") or 0) / 100
        sl = round(price * (1 - sl_pct), 4) if sl_pct else None
        tp = round(price * (1 + tp_pct), 4) if tp_pct else None
        if side == "sell":
            sl, tp = (round(price * (1 + sl_pct), 4) if sl_pct else None,
                      round(price * (1 - tp_pct), 4) if tp_pct else None)
        try:
            result = conn.place_order(
                symbol=self._map_symbol(symbol), side=side, volume=volume,
                price=price if conn.mode == "simulation" else None,
                sl=sl, tp=tp, comment="TraderDesk/%s" % (fp or "order")[:12],
                magic=self.settings.get("mt5").get("magic"),
            )
            ticket_id = result.get("ticket") or result.get("order") or "—"
            fill_price = float(result.get("price") or price)
            self._tool("trader-broker", ["result", "--index", idx, "--status", "placed",
                                         "--broker-id", str(ticket_id),
                                         "--filled-qty", str(volume),
                                         "--filled-price", str(fill_price)])
            rec = {
                "id": fp, "fingerprint": fp, "time": now(), "symbol": symbol,
                "mt5_symbol": self._map_symbol(symbol), "side": side, "volume": volume,
                "notional": round(notional, 2), "price": round(fill_price, 4),
                "sl": sl, "tp": tp, "ticket": ticket_id, "status": "filled",
                "mode": conn.mode, "risk": "PASS",
                "trail": "copycat → budget → risk → broker → MT5",
            }
            self.store.add_order(rec)
            self.store.counters["executions"] += 1
            self.store.log("ORDRE MT5 #%s : %s %s %.2f @ %.4f (%.2f $) — %s" %
                           (ticket_id, side.upper(), rec["mt5_symbol"], volume, fill_price, notional,
                            conn.mode), "trade", "trader-broker")
            self._refresh_account()
            return {"ok": True, "order": rec}
        except Exception as e:  # noqa: BLE001
            self._tool("trader-broker", ["result", "--index", idx, "--status", "failed",
                                         "--note", str(e)[:100]])
            self.store.log("Échec de l'envoi MT5 pour %s : %s" % (symbol, e), "error", "trader-broker")
            self.store.add_order({"id": fp, "fingerprint": fp, "time": now(), "symbol": symbol,
                                  "side": side, "status": "failed", "error": str(e)[:200]})
            return {"ok": False, "reason": str(e)}

    def execute_orders(self):
        t = self.settings.get("trading")
        if not self.tickets:
            self.tickets = (read_json(self.state_dir / "tickets.json", {}) or {}).get("tickets", [])
        ready = [x for x in self.tickets if x.get("ready")]
        if not ready:
            return {"executed": 0, "pending": 0, "reason": "aucun ticket READY"}
        gate = self._gates()
        if t.get("require_approval"):
            self.store.log("%d ordre(s) en attente de votre approbation (mode manuel)" % len(ready),
                           "warn", "trader-broker")
            return {"executed": 0, "pending": len(ready), "reason": "approbation manuelle requise"}
        if not t.get("auto_execute"):
            return {"executed": 0, "pending": len(ready), "reason": "exécution automatique désactivée"}
        if gate:
            self.store.log("Exécution bloquée : %s" % gate, "warn", "trader-broker")
            return {"executed": 0, "pending": len(ready), "reason": gate}
        done, errors = 0, []
        limit = int(t.get("max_orders_per_cycle") or 5)
        for ticket in ready[:limit]:
            r = self._execute_ticket(ticket)
            if r.get("ok"):
                done += 1
            elif not r.get("skipped") and r.get("reason"):
                errors.append(r["reason"])
        if done:
            self.refresh_tickets()
            self.store.refresh_artifacts(ARTIFACT_NAMES)
        return {"executed": done, "errors": errors, "pending": 0}

    def _post_execution_refresh(self):
        """Après des fills, tax et rebalance relisent le nouveau portefeuille."""
        for aid in ("trader-tax", "trader-rebalance"):
            if self.store.agents[aid].get("enabled", True):
                self.run_agent(aid)
        self.store.refresh_artifacts(ARTIFACT_NAMES)

    def approve_order(self, fingerprint):
        ticket = next((x for x in self.tickets if x.get("fingerprint") == fingerprint), None)
        if not ticket:
            return {"ok": False, "error": "ticket introuvable ou expiré"}
        if not ticket.get("ready"):
            return {"ok": False, "error": "ce ticket n'est plus READY (relancez risk + broker)"}
        result = self._execute_ticket(ticket, force=True)
        if result.get("ok"):
            self.refresh_tickets()
            self.store.refresh_artifacts(ARTIFACT_NAMES)
        return result

    def reject_order(self, fingerprint):
        ticket = next((x for x in self.tickets if x.get("fingerprint") == fingerprint), None)
        if not ticket:
            return {"ok": False, "error": "ticket introuvable"}
        rc, out, err = self._tool("trader-broker", ["decline", "--index", ticket.get("index"),
                                                    "--reply", "no"])
        self.store.log("Ordre %s refusé par l'utilisateur" % fingerprint, "warn", "trader-broker")
        return {"ok": rc == 0, "output": (out or err).strip()[:300]}

    # ------------------------------------------------------------------ boucle
    def _loop(self):
        self.seed()
        self.store.log("TraderDesk démarré — 11 agents chargés, dossier %s" % self.trader,
                       "success", "system")
        self.connect()
        self.enqueue(self.run_pipeline)
        last_cycle = time.monotonic()
        last_tick = 0.0
        last_retry = 0.0
        cycle_seconds = 90
        while not self._stop.wait(1):
            try:
                t = self.settings.get("trading")
                mt5 = self.settings.get("mt5")
                cycle_seconds = max(20, int(t.get("cycle_seconds") or 90))
                conn = self.connectors.current
                if time.monotonic() - last_tick >= 5:
                    last_tick = time.monotonic()
                    if conn and conn.connected:
                        conn.tick()
                        self._refresh_account()
                if (self.store.connection.get("state") != "connected" and mt5.get("auto_connect")
                        and time.monotonic() - last_retry >= max(5, int(mt5.get("reconnect_seconds") or 15))):
                    last_retry = time.monotonic()
                    self.store.connection["next_retry"] = "reconnexion en cours"
                    self.enqueue(self.connect)
                if time.monotonic() - last_cycle >= cycle_seconds and not self.pipeline_running:
                    last_cycle = time.monotonic()
                    self.enqueue(self.run_pipeline)
            except Exception as e:  # noqa: BLE001
                self.store.log("Boucle moteur : %s" % e, "error", "system")
