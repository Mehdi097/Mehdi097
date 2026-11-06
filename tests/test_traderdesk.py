"""Tests de fumée : registre, connecteurs, pipeline complet, API HTTP.

    python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="traderdesk-test-")
os.environ["TRADERDESK_HOME"] = TMP

from traderdesk.settings import Settings, RUNTIME_DIR, SKILLS_DIR  # noqa: E402
from traderdesk.state import Store  # noqa: E402
from traderdesk.agents.registry import AGENTS, AGENTS_BY_ID, skill_markdown  # noqa: E402
from traderdesk.mt5 import ConnectorManager, SimulationConnector  # noqa: E402
from traderdesk.mt5.bridge import Bridge, make_handler  # noqa: E402
from traderdesk.mt5.connector import RestConnector, normalize_address  # noqa: E402
from traderdesk.agents.engine import Engine  # noqa: E402
from traderdesk.server import serve  # noqa: E402


def clean_runtime():
    for name in ("settings.json", "appstate.json", "trader"):
        p = RUNTIME_DIR / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


def fresh():
    clean_runtime()
    s = Settings()
    st = Store(list(AGENTS_BY_ID))
    st.reset_demo()
    cm = ConnectorManager(s, st)
    e = Engine(s, st, cm)
    e.seed(force=True)
    return s, st, cm, e


class RegistryTests(unittest.TestCase):
    def test_eleven_agents_complete(self):
        self.assertEqual(len(AGENTS), 11)
        for a in AGENTS:
            self.assertTrue((SKILLS_DIR / a["id"] / "SKILL.md").exists(), a["id"])
            self.assertTrue((SKILLS_DIR / a["tool"]).exists(), a["id"])
            for field in ("role", "detail", "commands", "reads", "writes", "rules",
                          "example", "never", "stage", "triggers"):
                self.assertTrue(a[field], "%s.%s" % (a["id"], field))
        self.assertIn("trader-copycat", skill_markdown("trader-copycat"))


class ConnectorTests(unittest.TestCase):
    def test_simulation_account_and_order(self):
        c = SimulationConnector({}, initial_balance=5000,
                                state_path=os.path.join(TMP, "sim-unit.json"))
        self.assertTrue(c.connect()["connected"])
        r = c.place_order(symbol="AAPL", side="buy", volume=3.66, price=341.27)
        self.assertEqual(r["ticket"], 900001)
        self.assertEqual(len(c.positions()), 1)
        self.assertAlmostEqual(c.account()["equity"], 5000.0, delta=1)
        c.tick()
        self.assertIn("profit", c.account())
        self.assertEqual(c.close_position(900001)["status"], "closed")

    def test_simulation_state_survives_restart(self):
        path = os.path.join(TMP, "sim-restart.json")
        c = SimulationConnector({}, initial_balance=5000, state_path=path)
        c.connect()
        c.place_order(symbol="KO", side="buy", volume=7.86, price=90.11)
        c2 = SimulationConnector({}, initial_balance=5000, state_path=path)
        c2.connect()
        self.assertEqual(len(c2.positions()), 1)
        self.assertEqual(c2.positions()[0]["symbol"], "KO")
        self.assertLess(c2.account()["balance"], 5000)

    def test_address_normalization(self):
        self.assertEqual(normalize_address("192.168.1.5:8765"), "http://192.168.1.5:8765")
        self.assertEqual(normalize_address("https://mt5.local/"), "https://mt5.local")

    def test_rest_bridge_with_api_key(self):
        bridge = Bridge("cle-test")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bridge))
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            c = RestConnector({"address": "http://127.0.0.1:%d" % port,
                               "timeout": 5}, api_key="cle-test")
            self.assertTrue(c.connect()["connected"])
            self.assertIn("balance", c.account())
            order = c.place_order(symbol="BAC", side="buy", volume=1.0)
            self.assertTrue(order.get("ok", True))
            self.assertTrue(order.get("ticket"))
            bad = RestConnector({"address": "http://127.0.0.1:%d" % port}, api_key="fausse")
            with self.assertRaises(Exception):
                bad.connect()
        finally:
            httpd.shutdown()
            httpd.server_close()


class PipelineTests(unittest.TestCase):
    def test_full_cycle_places_five_orders(self):
        s, st, cm, e = fresh()
        self.assertTrue(e.connect()["ok"])
        r = e.run_pipeline()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["agents"]), 11)
        self.assertEqual(r["execution"]["executed"], 5)
        self.assertEqual(len(st.trades), 5)
        self.assertEqual(len(st.positions), 5)
        self.assertEqual(st.counters["blocks"], 0)
        tickets = (st.artifacts.get("trader/state/tickets.json") or {}).get("tickets", [])
        self.assertEqual(len(tickets), 5)
        self.assertFalse(any(t["ready"] for t in tickets))
        self.assertTrue((RUNTIME_DIR / "trader" / "portfolio.json").exists())
        pf = json.loads((RUNTIME_DIR / "trader" / "portfolio.json").read_text())
        self.assertTrue(all(p.get("lots") for p in pf["positions"]))
        self.assertTrue(any("PASS" in a["summary"] for k, a in st.agents.items()
                            if k == "trader-risk"))

    def test_risk_blocks_when_no_cash_left(self):
        s, st, cm, e = fresh()
        e.connect()
        e.run_pipeline()
        e.run_pipeline()
        self.assertGreater(st.counters["blocks"], 0)
        self.assertIn("BLOCK", st.agents["trader-risk"]["summary"])

    def test_settings_never_expose_secrets(self):
        s, st, cm, e = fresh()
        s.update({"mt5": {"api_key": "supersecret1234", "password": "mdp"}})
        pub = s.public()["mt5"]
        self.assertNotIn("supersecret1234", pub["api_key"])
        self.assertTrue(pub["has_api_key"])
        self.assertTrue(s.secret("api_key").startswith("supersecret"))


class ApiTests(unittest.TestCase):
    def test_http_endpoints(self):
        s, st, cm, e = fresh()
        httpd = serve("127.0.0.1", 0, settings=s, store=st, engine=e)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = "http://127.0.0.1:%d" % port
        try:
            def get(path):
                with urllib.request.urlopen(base + path, timeout=5) as r:
                    return r.status, r.read().decode("utf-8")
            code, body = get("/api/health")
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)["ok"])
            code, body = get("/api/state")
            state = json.loads(body)
            self.assertEqual(len(state["agents_spec"]), 11)
            self.assertNotIn("supersecret", body)
            code, body = get("/api/docs/trader-risk")
            self.assertEqual(code, 200)
            self.assertIn("trader-risk", body)
            code, body = get("/")
            self.assertIn("TraderDesk", body)
            req = urllib.request.Request(base + "/api/toggle",
                                         data=json.dumps({"section": "trading", "key": "kill_switch"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertTrue(json.loads(r.read())["value"])
            self.assertTrue(s.get("trading")["kill_switch"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
