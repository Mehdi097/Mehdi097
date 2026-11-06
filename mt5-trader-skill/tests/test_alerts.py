"""Alert evaluation, the once/cooldown state, and the session clock."""

import datetime
import json
import os
import tempfile
import unittest

import _load

alerts = _load.load("mt5-alerts", "alerts")


class TestSessions(unittest.TestCase):
    def test_windows(self):
        self.assertTrue(alerts.in_session(10, "london"))
        self.assertFalse(alerts.in_session(10, "newyork"))
        self.assertTrue(alerts.in_session(23, "sydney"))     # wraps midnight
        self.assertTrue(alerts.in_session(2, "sydney"))
        self.assertFalse(alerts.in_session(12, "sydney"))

    def test_state_and_next(self):
        now = datetime.datetime(2026, 11, 6, 13, 0, tzinfo=datetime.timezone.utc)
        state = alerts.session_state(now)
        self.assertTrue(state["london"])
        self.assertTrue(state["newyork"])
        nxt = alerts.session_boundaries(now)
        self.assertEqual(nxt["newyork_close"], 8 * 60)
        self.assertIn("tokyo_open", nxt)


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = _load.make_trader(cls.tmp)
        cls.b = _load.bridge_for(cls.root)
        cls.now = datetime.datetime(2026, 11, 6, 12, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def tearDownClass(cls):
        cls.b.shutdown()
        _load.cleanup(cls.tmp)

    def test_price_alerts(self):
        mid = self.b.tick("EURUSD")["mid"]
        fired, message = alerts.evaluate(
            {"type": "price_above", "symbol": "EURUSD", "level": mid - 0.01}, self.b, self.now)
        self.assertTrue(fired, message)
        fired, _ = alerts.evaluate(
            {"type": "price_above", "symbol": "EURUSD", "level": mid + 1.0}, self.b, self.now)
        self.assertFalse(fired)
        fired, _ = alerts.evaluate(
            {"type": "price_below", "symbol": "EURUSD", "level": mid + 1.0}, self.b, self.now)
        self.assertTrue(fired)

    def test_spread_alerts(self):
        fired, message = alerts.evaluate(
            {"type": "spread_above", "symbol": "EURUSD", "points": 5}, self.b, self.now)
        self.assertTrue(fired, message)
        fired, _ = alerts.evaluate(
            {"type": "spread_above", "symbol": "EURUSD", "points": 50}, self.b, self.now)
        self.assertFalse(fired)

    def test_pips_move(self):
        fired, message = alerts.evaluate(
            {"type": "pips_move", "symbol": "EURUSD", "pips": 1, "window_min": 600},
            self.b, self.now)
        self.assertIsInstance(fired, bool)
        self.assertIn("EURUSD", message)

    def test_margin_and_floating(self):
        fired, message = alerts.evaluate(
            {"type": "margin_level_below", "level": 100000}, self.b, self.now)
        self.assertTrue(fired, message)
        fired, _ = alerts.evaluate(
            {"type": "floating_profit_above", "level": -1000000}, self.b, self.now)
        self.assertTrue(fired)

    def test_session_alert(self):
        fired, message = alerts.evaluate(
            {"type": "session", "session": "london", "event": "open", "within_min": 5},
            self.b, self.now)
        self.assertFalse(fired)      # it is 12:00, London opened five hours ago
        self.assertIn("London", message)

    def test_bad_alert_does_not_crash(self):
        fired, message = alerts.evaluate({"type": "nonsense"}, self.b, self.now)
        self.assertFalse(fired)
        self.assertIn("unknown", message)
        fired, message = alerts.evaluate({"type": "price_above", "symbol": "NOPE"},
                                         self.b, self.now)
        self.assertFalse(fired)


class TestStateFile(unittest.TestCase):
    def test_once_and_cooldown(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            b = _load.bridge_for(root)
            mid = b.tick("EURUSD")["mid"]
            cfg = {"alerts": [{"id": "a", "symbol": "EURUSD", "type": "price_above",
                               "level": mid - 0.01, "once": True}]}
            _load.write_json(os.path.join(root, "alerts.json"), cfg)
            self.assertEqual(_load.run(alerts, ["--trader-dir", root, "--offline"]), 1)
            self.assertEqual(_load.run(alerts, ["--trader-dir", root, "--offline"]), 0)
            state = _load.read_json(os.path.join(root, "state", "alerts.json"))
            self.assertEqual(state["fired"]["a"]["count"], 1)
            self.assertEqual(_load.run(alerts, ["--trader-dir", root, "--offline", "--reset"]), 0)
            self.assertEqual(_load.run(alerts, ["--trader-dir", root, "--offline"]), 1)
            b.shutdown()
        finally:
            _load.cleanup(tmp)

    def test_clock_runs(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            self.assertEqual(_load.run(alerts, ["clock", "--trader-dir", root, "--offline"]), 0)
        finally:
            _load.cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
