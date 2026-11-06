"""The chain that matters: budget -> risk -> broker, entirely offline."""

import json
import os
import tempfile
import unittest

import _load

size = _load.load("mt5-budget", "size")
check = _load.load("mt5-risk", "check")
execute = _load.load("mt5-broker", "execute")

TARGETS = {"source": "test", "targets": [
    {"symbol": "EURUSD", "side": "buy", "weight": 50, "stop_pips": 20, "tp_pips": 40},
    {"symbol": "XAUUSD", "side": "buy", "weight": 30, "stop_pips": 20, "tp_pips": 40},
    {"symbol": "US30", "side": "sell", "weight": 20, "stop_pips": 20, "tp_pips": 40},
]}


def order(**over):
    base = {"id": "EURUSD-buy-test", "symbol": "EURUSD", "side": "buy", "type": "market",
            "volume": 0.10, "sl": 1.07790, "tp": 1.08390, "stop_pips": 20.0,
            "magic": 20261106, "deviation": 20}
    base.update(over)
    return base


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = _load.make_trader(self.tmp, targets=TARGETS)

    def tearDown(self):
        _load.cleanup(self.tmp)

    def test_weights_are_normalised(self):
        rows = size.read_targets(os.path.join(self.root, "targets.json"))
        self.assertAlmostEqual(sum(t["weight"] for t in rows), 100.0, places=3)

    def test_plan_sizes_by_risk(self):
        b = _load.bridge_for(self.root)
        targets = size.read_targets(os.path.join(self.root, "targets.json"))
        orders, skills = [], []
        for target in targets:
            o, why = size.plan_order(b, target, b.cfg, 10000.0)
            (orders.append(o) if o else skills.append(why))
        self.assertEqual(len(orders), 3, skills)
        eur = [o for o in orders if o["symbol"] == "EURUSD"][0]
        self.assertAlmostEqual(eur["risk_pct"], 1.0, places=2)     # 1.5% capped at 1%
        # 1% of 10k = 100 risk, 20 pips at 1 USD/point = 200 per lot
        self.assertAlmostEqual(eur["volume"], 0.5, places=2)
        self.assertLess(eur["sl"], eur["entry_ref"])
        self.assertGreater(eur["tp"], eur["entry_ref"])
        self.assertEqual(eur["type"], "market")

    def test_sell_target_puts_stops_above(self):
        b = _load.bridge_for(self.root)
        target = {"symbol": "US30", "side": "sell", "weight": 100,
                  "stop_pips": 20, "tp_pips": 40}
        o, why = size.plan_order(b, target, b.cfg, 10000.0)
        self.assertIsNotNone(o, why)
        self.assertGreater(o["sl"], o["entry_ref"])
        self.assertLess(o["tp"], o["entry_ref"])

    def test_min_lot_too_big_is_skipped(self):
        b = _load.bridge_for(self.root)
        target = {"symbol": "XAUUSD", "side": "buy", "weight": 100,
                  "stop_pips": 900, "tp_pips": 1800}
        o, why = size.plan_order(b, target, b.cfg, 300.0)
        self.assertIsNone(o)
        self.assertIn("min lot", why.lower())

    def test_write_orders_end_to_end(self):
        _load.run(size, ["--trader-dir", self.root, "--offline", "--write"])
        payload = _load.read_json(os.path.join(self.root, "orders.json"))
        self.assertEqual(len(payload["orders"]), 3)
        self.assertGreater(payload["total_lots"], 0)
        self.assertLessEqual(payload["total_lots"], 3.0)
        for o in payload["orders"]:
            self.assertEqual(o["magic"], 20261106)
            self.assertTrue(o["id"])
            self.assertLess(o["volume"], 100)

    def test_fixed_lot(self):
        b = _load.bridge_for(self.root)
        target = {"symbol": "EURUSD", "side": "buy", "weight": 100, "stop_pips": 20}
        o, why = size.plan_order(b, target, b.cfg, 10000.0, fixed_lot=0.05)
        self.assertIsNotNone(o, why)
        self.assertAlmostEqual(o["volume"], 0.05)


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = _load.make_trader(self.tmp, orders=[order()], positions=[],
                                     config={"max_spread_points": 30})

    def tearDown(self):
        _load.cleanup(self.tmp)

    def run_check(self, orders=None, config=None):
        if orders is not None:
            _load.write_json(os.path.join(self.root, "orders.json"), {"orders": orders})
        if config:
            cfg = _load.read_json(os.path.join(self.root, "config.json"))
            cfg.update(config)
            _load.write_json(os.path.join(self.root, "config.json"), cfg)
        code = _load.run(check, ["--trader-dir", self.root])
        risk = _load.read_json(os.path.join(self.root, "state", "risk.json"))
        return code, risk

    def verdicts(self, risk):
        return [r["verdict"] for r in risk["results"]]

    def test_clean_order_passes(self):
        code, risk = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(self.verdicts(risk), ["PASS"])
        self.assertEqual(risk["date"], check.utc_today())
        self.assertTrue(risk["results"][0]["fingerprint"])

    def test_missing_sl_blocks(self):
        code, risk = self.run_check([order(sl=None, tp=None)])
        self.assertEqual(code, 1)
        self.assertEqual(self.verdicts(risk), ["BLOCK"])
        self.assertIn("stop", " ".join(risk["results"][0]["reasons"]).lower())

    def test_volume_over_cap_blocks(self):
        code, risk = self.run_check([order(volume=5.0)])
        self.assertEqual(code, 1)
        self.assertIn("max_lots_per_order", " ".join(risk["results"][0]["reasons"]))

    def test_off_step_volume_blocks(self):
        code, risk = self.run_check([order(volume=0.015)])
        self.assertEqual(code, 1)
        self.assertIn("lot step", " ".join(risk["results"][0]["reasons"]))

    def test_risk_percent_blocks(self):
        # 1.0 lot on a 20 pip stop = 200 USD = 2% of a 10k account
        code, risk = self.run_check([order(volume=1.0)])
        self.assertEqual(code, 1)
        self.assertIn("max 1.00%", " ".join(risk["results"][0]["reasons"]))

    def test_spread_blocks(self):
        code, risk = self.run_check(config={"max_spread_points": 3})
        self.assertEqual(code, 1)
        self.assertIn("spread", " ".join(risk["results"][0]["reasons"]))

    def test_reward_risk_blocks(self):
        code, risk = self.run_check([order(tp=1.07910)])   # 6 pips for 20 risked
        self.assertEqual(code, 1)
        self.assertIn("reward:risk", " ".join(risk["results"][0]["reasons"]))

    def test_blocked_symbol(self):
        code, risk = self.run_check([order(symbol="EURUSD")],
                                    config={"blocked_symbols": ["EURUSD"]})
        self.assertEqual(code, 1)
        self.assertIn("blocked", " ".join(risk["results"][0]["reasons"]))

    def test_wrong_sl_side(self):
        code, risk = self.run_check([order(sl=1.08500)])
        self.assertEqual(code, 1)
        self.assertIn("below entry", " ".join(risk["results"][0]["reasons"]))

    def test_duplicate_in_batch_blocks_second(self):
        code, risk = self.run_check([order(id="a"), order(id="b")])
        self.assertEqual(code, 1)
        self.assertEqual(self.verdicts(risk), ["PASS", "BLOCK"])
        self.assertIn("already", " ".join(risk["results"][1]["reasons"]))

    def test_pending_needs_price(self):
        code, risk = self.run_check([order(type="limit", price=None)])
        self.assertEqual(code, 1)
        self.assertIn("pending order needs a price", " ".join(risk["results"][0]["reasons"]))

    def test_pending_can_be_disallowed(self):
        code, risk = self.run_check([order(type="limit", price=1.07000)],
                                    config={"allow_pending": False})
        self.assertEqual(code, 1)
        self.assertIn("allow_pending", " ".join(risk["results"][0]["reasons"]))

    def test_kill_switch_blocks_everything(self):
        open(os.path.join(self.root, "state", "KILL"), "w").close()
        code, risk = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("KILL", " ".join(risk["results"][0]["reasons"]))
        self.assertTrue(risk["global_blocks"])

    def test_drawdown_blocks_everything(self):
        _load.write_json(os.path.join(self.root, "state", "equity_peak.json"),
                         {"peak_equity": 20000.0})
        code, risk = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("drawdown", " ".join(risk["results"][0]["reasons"]).lower())

    def test_daily_loss_blocks_everything(self):
        import datetime
        snap = _load.read_json(os.path.join(self.root, "data", "snapshot.json"))
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        snap["deals"].append({"ticket": 9, "position_id": 9, "symbol": "EURUSD", "type": 0,
                              "entry": 1, "volume": 1.0, "price": 1.08, "profit": -300.0,
                              "commission": 0.0, "swap": 0.0, "magic": 1, "time": now})
        _load.write_json(os.path.join(self.root, "data", "snapshot.json"), snap)
        code, risk = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("daily loss", " ".join(risk["results"][0]["reasons"]).lower())

    def test_real_account_blocks_without_allow_live(self):
        snap = _load.read_json(os.path.join(self.root, "data", "snapshot.json"))
        snap["account"]["is_real"] = True
        snap["account"]["trade_mode"] = 2
        _load.write_json(os.path.join(self.root, "data", "snapshot.json"), snap)
        code, risk = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("REAL", " ".join(risk["results"][0]["reasons"]))

    def test_news_blackout_blocks(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        cal = {"blackouts": [{"title": "Nonfarm Payrolls", "currency": "USD", "impact": "high",
                              "from": (now - datetime.timedelta(minutes=5)).isoformat(),
                              "to": (now + datetime.timedelta(minutes=25)).isoformat()}]}
        _load.write_json(os.path.join(self.root, "calendar.json"), cal)
        code, risk = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("blackout", " ".join(risk["results"][0]["reasons"]))


class TestBroker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = _load.make_trader(self.tmp, targets=TARGETS, orders=[order()], positions=[])

    def tearDown(self):
        _load.cleanup(self.tmp)

    def test_yes_parser(self):
        for reply in ("yes", "Yes", "wah", "iyyeh", "ok", "safi", "yes please"):
            self.assertTrue(execute.is_real_yes(reply)[0], reply)
        for reply in ("yes to all", "ok, all of them", "sure", "no", "yes but wait",
                      "yes unless it drops", "la", "", "yes and also the other one",
                      "maybe yes", "yesterday's trade"):
            self.assertFalse(execute.is_real_yes(reply)[0], reply)

    def test_fingerprint_is_stable_and_specific(self):
        a = execute.fingerprint(order())
        b = execute.fingerprint(dict(order()))
        self.assertEqual(a, b)
        self.assertNotEqual(a, execute.fingerprint(order(volume=0.11)))
        self.assertNotEqual(a, execute.fingerprint(order(sl=1.0778)))

    def test_not_ready_without_risk(self):
        b = _load.bridge_for(self.root)
        state = execute.load_state(self.root)
        ticket = execute.ticket(order(), {}, state, b)
        self.assertEqual(ticket["status"], "NOT READY")

    def test_cannot_approve_blocked(self):
        _load.run(check, ["--trader-dir", self.root])
        b = _load.bridge_for(self.root)
        state = execute.load_state(self.root)
        risk = execute.load_risk(self.root)
        ticket = execute.ticket(order(), risk, state, b)
        self.assertEqual(ticket["status"], "READY")
        self.assertEqual(ticket["request"]["symbol"], "EURUSD")
        self.assertGreater(ticket["request"]["price"], 0)

    def test_full_chain_offline(self):
        _load.run(check, ["--trader-dir", self.root])
        code = _load.run(execute, ["approve", "--trader-dir", self.root, "--id", "EURUSD-buy-test",
                             "--reply", "yes"])
        self.assertEqual(code, 0)
        dry = _load.run(execute, ["send", "--trader-dir", self.root, "--id", "EURUSD-buy-test",
                            "--dry-run"])
        self.assertEqual(dry, 0)
        sent = _load.run(execute, ["send", "--trader-dir", self.root, "--id", "EURUSD-buy-test"])
        self.assertEqual(sent, 0)
        state = execute.load_state(self.root)
        actions = [d["action"] for d in state["decisions"]]
        self.assertEqual(actions, ["approved", "sent"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "state", "journal.jsonl")))

    def test_cannot_send_without_approval(self):
        _load.run(check, ["--trader-dir", self.root])
        code = _load.run(execute, ["send", "--trader-dir", self.root, "--id", "EURUSD-buy-test"])
        self.assertEqual(code, 2)

    def test_batch_yes_is_refused(self):
        _load.run(check, ["--trader-dir", self.root])
        code = _load.run(execute, ["approve", "--trader-dir", self.root, "--id", "EURUSD-buy-test",
                             "--reply", "yes to all"])
        self.assertEqual(code, 2)

    def test_cannot_send_after_kill(self):
        _load.run(check, ["--trader-dir", self.root])
        _load.run(execute, ["approve", "--trader-dir", self.root, "--id", "EURUSD-buy-test",
                      "--reply", "yes"])
        open(os.path.join(self.root, "state", "KILL"), "w").close()
        code = _load.run(execute, ["send", "--trader-dir", self.root, "--id", "EURUSD-buy-test"])
        self.assertEqual(code, 2)

    def test_status_runs(self):
        self.assertEqual(_load.run(execute, ["status", "--trader-dir", self.root]), 0)


if __name__ == "__main__":
    unittest.main()
