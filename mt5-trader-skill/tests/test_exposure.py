"""Exposure, currency tilt, drift and the rebalance proposals."""

import tempfile
import unittest

import _load

rebalance = _load.load("mt5-exposure", "rebalance")


class TestExposureOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = _load.make_trader(cls.tmp)
        cls.b = _load.bridge_for(cls.root)
        cls.positions = cls.b.positions()
        cls.exposure, cls.total = rebalance.build_exposure(cls.b, cls.positions)

    @classmethod
    def tearDownClass(cls):
        cls.b.shutdown()
        _load.cleanup(cls.tmp)

    def test_signed_lots(self):
        self.assertAlmostEqual(self.exposure["EURUSD"]["lots"], 0.05, places=4)
        self.assertAlmostEqual(self.exposure["US30"]["lots"], -0.20, places=4)

    def test_money_per_point_follows_the_net_position(self):
        eur = self.exposure["EURUSD"]
        self.assertAlmostEqual(eur["money_per_point"], 0.05 * 1.0, places=4)
        self.assertLess(self.exposure["US30"]["money_per_point"], 0)

    def test_shares_sum_to_100(self):
        total_share = sum(row.get("share_pct") or 0 for row in self.exposure.values())
        self.assertAlmostEqual(total_share, 100.0, places=1)

    def test_floating_included(self):
        self.assertAlmostEqual(self.exposure["EURUSD"]["floating"], 4.15, places=2)

    def test_hedged_flag(self):
        exposure, _ = rebalance.build_exposure(self.b, [
            {"ticket": 1, "symbol": "EURUSD", "side": "buy", "volume": 0.1, "profit": 0},
            {"ticket": 2, "symbol": "EURUSD", "side": "sell", "volume": 0.1, "profit": 0},
        ])
        self.assertTrue(exposure["EURUSD"]["hedged"])
        self.assertAlmostEqual(exposure["EURUSD"]["lots"], 0.0, places=6)

    def test_currency_tilt_signs(self):
        tilt = rebalance.currency_tilt(self.b, self.exposure, self.total)
        self.assertIn("EUR", tilt)
        self.assertIn("USD", tilt)
        self.assertGreater(tilt["EUR"]["units"], 0)     # long EUR
        self.assertLess(tilt["USD"]["units"], 0)        # short USD against it
        self.assertNotIn("USA30", tilt)                 # indices are not a currency leg

    def test_notional_quality_is_honest(self):
        self.assertEqual(self.exposure["EURUSD"]["notional_quality"], "exact")


class TestDrift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = _load.make_trader(self.tmp, targets={"targets": [
            {"symbol": "EURUSD", "side": "buy", "weight": 20, "stop_pips": 20},
            {"symbol": "XAUUSD", "side": "buy", "weight": 50, "stop_pips": 20},
            {"symbol": "US30", "side": "sell", "weight": 30, "stop_pips": 20},
        ]})
        self.b = _load.bridge_for(self.root)

    def tearDown(self):
        self.b.shutdown()
        _load.cleanup(self.tmp)

    def test_drift_rows(self):
        exposure, total = rebalance.build_exposure(self.b, self.b.positions())
        rows = rebalance.drift(self.b, exposure, total,
                               self.root + "/targets.json")
        self.assertEqual(sorted(r["symbol"] for r in rows), ["EURUSD", "US30", "XAUUSD"])
        by_sym = {r["symbol"]: r for r in rows}
        self.assertGreater(by_sym["EURUSD"]["drift"], 0)      # holding it, target 20%
        self.assertLess(by_sym["XAUUSD"]["drift"], 0)         # not holding it, target 50%
        self.assertAlmostEqual(sum(r["target_weight"] for r in rows), 100.0, places=2)

    def test_proposals_respect_the_band(self):
        exposure, total = rebalance.build_exposure(self.b, self.b.positions())
        rows = rebalance.drift(self.b, exposure, total, self.root + "/targets.json")
        orders = rebalance.propose_orders(self.b, rows, band=5.0, equity=10000.0)
        self.assertTrue(orders)
        for order in orders:
            self.assertIn(order["side"], ("buy", "sell"))
            self.assertGreater(order["volume"], 0)
            self.assertLess(order["volume"], 100)
            if order["side"] == "buy":
                self.assertLess(order["sl"], order["entry_ref"])
            else:
                self.assertGreater(order["sl"], order["entry_ref"])

    def test_band_filters_everything_out(self):
        exposure, total = rebalance.build_exposure(self.b, self.b.positions())
        rows = rebalance.drift(self.b, exposure, total, self.root + "/targets.json")
        self.assertEqual(rebalance.propose_orders(self.b, rows, band=1000.0, equity=10000.0), [])

    def test_no_targets_is_not_an_error(self):
        self.assertIsNone(rebalance.drift(self.b, {}, 0, self.root + "/nope.json"))


if __name__ == "__main__":
    unittest.main()
