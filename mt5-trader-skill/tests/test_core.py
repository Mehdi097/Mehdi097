import datetime
import json
import os
import tempfile
import unittest

import _load

sizing = _load.load("mt5-core", "sizing")


def spec(**over):
    base = {
        "name": "EURUSD", "digits": 5, "point": 0.00001, "pip": 0.0001,
        "tick_size": 0.00001, "tick_value": 1.0, "value_per_point": 1.0,
        "contract_size": 100000, "volume_min": 0.01, "volume_max": 100.0,
        "volume_step": 0.01, "stops_level_points": 0, "freeze_level_points": 0,
        "spread_points": 8, "filling_mode_mask": 3,
    }
    base.update(over)
    return base


class TestUnits(unittest.TestCase):
    def test_pips(self):
        self.assertAlmostEqual(sizing.pip_size(spec()), 0.0001)
        jpy = spec(digits=3, point=0.001, pip=0.01)
        self.assertAlmostEqual(sizing.pip_size(jpy), 0.01)
        gold = spec(digits=2, point=0.01, pip=0.1)
        self.assertAlmostEqual(sizing.pip_size(gold), 0.1)
        index = spec(digits=1, point=0.1, pip=1.0)
        self.assertAlmostEqual(sizing.pip_size(index), 1.0)

    def test_price_conversions(self):
        s = spec()
        self.assertAlmostEqual(sizing.pips_to_price(s, 20), 0.0020)
        self.assertAlmostEqual(sizing.price_to_pips(s, 0.0020), 20.0)
        self.assertAlmostEqual(sizing.price_to_points(s, 0.0020), 200.0)

    def test_value_per_point(self):
        self.assertAlmostEqual(sizing.value_per_point(spec()), 1.0)
        # XAUUSD: 1 dollar per tick of 0.01 -> 100 per dollar of price
        gold = spec(digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
                    value_per_point=0.0, contract_size=100)
        self.assertAlmostEqual(sizing.value_per_point(gold), 1.0)
        # a spec with no tick value falls back to contract x point
        bare = spec(tick_value=0.0, value_per_point=0.0, contract_size=100000)
        self.assertAlmostEqual(sizing.value_per_point(bare), 1.0)


class TestVolume(unittest.TestCase):
    def test_normalise_down(self):
        self.assertEqual(sizing.normalise_volume(spec(), 0.256)[0], 0.25)
        self.assertEqual(sizing.normalise_volume(spec(), 0.0001)[0], 0.01)

    def test_normalise_step_and_max(self):
        s = spec(volume_step=0.1, volume_min=0.1, volume_max=5.0)
        self.assertEqual(sizing.normalise_volume(s, 0.37)[0], 0.3)
        self.assertEqual(sizing.normalise_volume(s, 99.0)[0], 5.0)

    def test_volume_for_risk(self):
        # 0.5% of 10,000 = 50 risk; 20 pips at 1 USD/point = 200 per lot -> 0.25
        volume, meta = sizing.volume_for_risk(10000, 0.5, 0.0020, spec())
        self.assertAlmostEqual(volume, 0.25)
        self.assertAlmostEqual(meta["risk_money"], 50.0)
        self.assertAlmostEqual(meta["actual_risk"], 50.0)
        self.assertFalse(meta["skipped"])

    def test_wider_stop_smaller_lot_same_money(self):
        tight, _ = sizing.volume_for_risk(10000, 1.0, 0.0010, spec())
        wide, _ = sizing.volume_for_risk(10000, 1.0, 0.0040, spec())
        self.assertAlmostEqual(tight, 1.0)
        self.assertAlmostEqual(wide, 0.25)
        self.assertAlmostEqual(tight * 100, wide * 400)

    def test_min_lot_skips_instead_of_rounding_up(self):
        volume, meta = sizing.volume_for_risk(100, 0.5, 0.0020, spec())
        self.assertEqual(volume, 0.0)
        self.assertTrue(meta["skipped"])
        self.assertIn("min lot", " ".join(meta["reasons"]).lower())

    def test_min_lot_override_is_honest(self):
        volume, meta = sizing.volume_for_risk(100, 0.5, 0.0020, spec(), allow_min_lot=True)
        self.assertEqual(volume, 0.01)
        self.assertGreater(meta["actual_risk_pct"], 0.5)
        self.assertEqual(meta["clamped"], "min")

    def test_max_volume_cap(self):
        volume, meta = sizing.volume_for_risk(100000, 5.0, 0.0010, spec(), max_volume=1.0)
        self.assertEqual(volume, 1.0)
        self.assertEqual(meta["clamped"], "cap")

    def test_volume_for_cash(self):
        volume, meta = sizing.volume_for_cash(1000, spec(), 1.08)
        self.assertAlmostEqual(volume, 0.01)   # 1000 / 108,000 = 0.0092 -> floors
        self.assertTrue(meta["skipped"] or volume == 0.01)

    def test_bad_inputs(self):
        with self.assertRaises(sizing.SizingError):
            sizing.volume_for_risk(0, 0.5, 0.0020, spec())
        with self.assertRaises(sizing.SizingError):
            sizing.volume_for_risk(1000, 0, 0.0020, spec())
        with self.assertRaises(sizing.SizingError):
            sizing.loss_per_lot(spec(), 0)


class TestStops(unittest.TestCase):
    def test_valid_buy(self):
        ok, issues, sl, tp = sizing.stops_ok(spec(), "buy", 1.08000, 1.07800, 1.08400)
        self.assertTrue(ok, issues)
        self.assertAlmostEqual(sizing.price_to_pips(spec(), sl), 20.0)

    def test_wrong_side(self):
        ok, issues, _, _ = sizing.stops_ok(spec(), "buy", 1.08000, 1.08200, None)
        self.assertFalse(ok)
        self.assertIn("below entry", " ".join(issues))

    def test_sell_side(self):
        ok, _, _, _ = sizing.stops_ok(spec(), "sell", 1.08000, 1.08200, 1.07600)
        self.assertTrue(ok)
        self.assertAlmostEqual(sizing.reward_risk(1.08, 1.082, 1.076), 2.0)

    def test_broker_minimum_distance(self):
        s = spec(stops_level_points=50)      # 50 points = 5 pips minimum
        ok, issues, _, _ = sizing.stops_ok(s, "buy", 1.08000, 1.07980, None)
        self.assertFalse(ok)
        self.assertIn("9rib", " ".join(issues))

    def test_spread_widens_the_minimum(self):
        s = spec(stops_level_points=0)
        ok, _, _, _ = sizing.stops_ok(s, "buy", 1.08000, 1.07990, None, spread_points=20)
        self.assertFalse(ok)

    def test_reward_risk_none_without_stops(self):
        self.assertIsNone(sizing.reward_risk(1.08, None, 1.09))


class TestLiveApiCalls(unittest.TestCase):
    """The MetaTrader5 package exposes history_deals_get only: no history_select_range.

    This is the exact call that crashed `journal` on a real terminal, so it gets
    a fake terminal and stays a test.
    """

    def test_deals_uses_history_deals_get(self):
        bridge = _load.load("mt5-core", "bridge")
        calls = {}

        class FakeMT5(object):
            TIMEFRAME_H1 = 16385

            def initialize(self, **kw):
                return True

            def shutdown(self):
                pass

            def last_error(self):
                return (0, "ok")

            def terminal_info(self):
                return {"trade_allowed": True, "connected": True, "build": 6304}

            def account_info(self):
                return {"login": 1, "server": "MetaQuotes-Demo", "trade_mode": 0,
                        "balance": 10000.0, "equity": 10000.0, "margin": 0.0,
                        "margin_free": 10000.0, "margin_level": 0.0, "profit": 0.0,
                        "currency": "USD", "leverage": 100}

            def history_deals_get(self, start, end):
                calls["deals"] = (start, end)
                return [{"ticket": 1, "position_id": 1, "profit": 5.0, "entry": 1, "time": 1}]

            def history_orders_get(self, start, end):
                calls["orders"] = (start, end)
                return ()

        fake = FakeMT5()
        self.assertFalse(hasattr(fake, "history_select_range"))
        old_avail, old_mt5 = bridge.MT5_AVAILABLE, bridge.mt5
        bridge.MT5_AVAILABLE, bridge.mt5 = True, fake
        tmp = tempfile.mkdtemp()
        try:
            b = bridge.Bridge(tmp, offline=False, config={"mode": "live", "login": 1})
            deals = b.deals()
            self.assertEqual(len(deals), 1)
            self.assertIn("deals", calls)
            start, end = calls["deals"]
            self.assertIsInstance(start, datetime.datetime)
            self.assertIsInstance(end, datetime.datetime)
            self.assertLess(start, end)
            self.assertEqual(b.history_orders(), [])
            b.shutdown()
        finally:
            bridge.MT5_AVAILABLE, bridge.mt5 = old_avail, old_mt5
            _load.cleanup(tmp)


class TestBridgeOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = _load.make_trader(cls.tmp)
        cls.b = _load.bridge_for(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.b.shutdown()
        _load.cleanup(cls.tmp)

    def test_mode(self):
        self.assertEqual(self.b.mode, "offline")

    def test_account(self):
        acct = self.b.account()
        self.assertEqual(acct["currency"], "USD")
        self.assertFalse(acct["is_real"])
        self.assertGreater(acct["equity"], 0)

    def test_spec_is_complete(self):
        s = self.b.spec("EURUSD")
        for key in ("digits", "point", "tick_value", "contract_size", "volume_min",
                    "volume_step", "filling_mode_mask", "value_per_point"):
            self.assertIn(key, s)
        self.assertEqual(s["digits"], 5)

    def test_unknown_symbol_raises(self):
        with self.assertRaises(Exception):
            self.b.spec("NOPEUSD")

    def test_tick_and_rates(self):
        tick = self.b.tick("EURUSD")
        self.assertGreater(tick["ask"], tick["bid"])
        self.assertEqual(tick["spread_points"], 8)
        bars = self.b.rates("EURUSD", "H1", 50)
        self.assertEqual(len(bars), 50)
        self.assertLess(bars[0]["low"], bars[0]["high"])

    def test_positions_and_deals(self):
        positions = self.b.positions()
        self.assertEqual(len(positions), 2)
        self.assertIn(positions[0]["side"], ("buy", "sell"))
        self.assertEqual(len(self.b.deals()), 16)

    def test_margin_positive(self):
        self.assertGreater(self.b.margin("EURUSD", 0.1), 0)

    def test_check_and_simulated_send(self):
        req = {"action": 1, "symbol": "EURUSD", "volume": 0.01, "type": 0,
               "price": 1.08, "sl": 1.07, "tp": 1.09, "deviation": 20,
               "magic": 1, "comment": "test", "type_time": 0, "type_filling": 0}
        check = self.b.check(req)
        self.assertEqual(check["retcode"], 0)
        result = self.b.send(req)
        self.assertTrue(result["ok"])
        self.assertTrue(result["simulated"])
        self.assertEqual(result["retcode"], 10009)
        self.assertTrue(os.path.exists(os.path.join(self.root, "state", "sim_fills.json")))

    def test_build_request_rounds_prices(self):
        bridge = _load.load("mt5-core", "bridge")
        req = bridge.build_request({"symbol": "EURUSD", "side": "buy", "type": "market",
                                    "volume": 0.1, "sl": 1.0779001, "tp": 1.0880002},
                                   self.b.spec("EURUSD"), self.b.tick("EURUSD"))
        self.assertEqual(req["sl"], 1.0779)
        self.assertEqual(req["price"], self.b.tick("EURUSD")["ask"])
        self.assertIn("type_filling", req)

    def test_snapshot_path_relative_to_the_trader_dir(self):
        """The exe can start from any CWD: "data/snapshot.json" means trader/data/."""
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            cfg = _load.read_json(os.path.join(root, "config.json"))
            cfg["offline_snapshot"] = "data/snapshot.json"      # relative, like the example
            _load.write_json(os.path.join(root, "config.json"), cfg)
            bridge = _load.load("mt5-core", "bridge")
            b = bridge.Bridge(root, offline=True)
            self.assertTrue(b._snapshot_path().endswith(os.path.join("trader", "data",
                                                                    "snapshot.json")))
            self.assertGreater(b.account()["equity"], 0)        # it really loaded
            b.shutdown()
        finally:
            _load.cleanup(tmp)

    def test_kill_switch_file(self):
        bridge = _load.load("mt5-core", "bridge")
        path = os.path.join(self.root, "state", "KILL")
        self.assertFalse(bridge.kill_switch(self.root))
        open(path, "w").close()
        self.assertTrue(bridge.kill_switch(self.root))
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
