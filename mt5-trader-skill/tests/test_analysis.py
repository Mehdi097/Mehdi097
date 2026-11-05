"""Indicators, the analyst report, and the screener rules."""

import os
import tempfile
import unittest

import _load

analyst = _load.load("mt5-analyst", "analyst")
screen = _load.load("mt5-screener", "screen")


class TestIndicators(unittest.TestCase):
    def test_ema_converges(self):
        values = [1.0] * 30
        self.assertAlmostEqual(analyst.ema(values, 10)[-1], 1.0)
        rising = list(range(1, 31))
        self.assertGreater(analyst.ema(rising, 10)[-1], analyst.ema(rising, 20)[-1])

    def test_rsi_extremes(self):
        up = [float(i) for i in range(1, 40)]
        self.assertGreater(analyst.rsi(up, 14), 90)
        down = [float(40 - i) for i in range(1, 40)]
        self.assertLess(analyst.rsi(down, 14), 10)
        self.assertIsNone(analyst.rsi([1.0, 2.0], 14))

    def test_atr_and_adr(self):
        bars = [{"high": 1.2, "low": 1.0, "close": 1.1} for _ in range(30)]
        self.assertAlmostEqual(analyst.atr(bars, 14), 0.2, places=6)
        self.assertAlmostEqual(analyst.adr(bars, 20), 0.2, places=6)
        self.assertIsNone(analyst.atr(bars[:5], 14))

    def test_percentile_and_slope(self):
        self.assertEqual(analyst.percentile_of_last([1, 2, 3, 100]), 100.0)
        self.assertEqual(analyst.percentile_of_last([1, 2, 3, 0]), 0.0)
        self.assertGreater(analyst.slope_pct(list(range(1, 30)), 10), 0)
        self.assertLess(analyst.slope_pct(list(range(30, 1, -1)), 10), 0)

    def test_trend_label(self):
        fast = analyst.ema(list(range(1, 60)), 20)
        slow = analyst.ema(list(range(1, 60)), 50)
        self.assertEqual(analyst.trend_label(fast, slow, 59), "up")
        self.assertEqual(analyst.trend_label(analyst.ema(list(range(60, 1, -1)), 20),
                                             analyst.ema(list(range(60, 1, -1)), 50), 2), "down")


class TestAnalystReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = _load.make_trader(cls.tmp)
        cls.b = _load.bridge_for(cls.root)
        cls.row = analyst.symbol_metrics(cls.b, "EURUSD", {"stop_atr_multiple": 1.5})

    @classmethod
    def tearDownClass(cls):
        cls.b.shutdown()
        _load.cleanup(cls.tmp)

    def test_row_has_the_numbers(self):
        for key in ("price", "atr_h1_pips", "adr20_pips", "rsi_h1", "trend_d1",
                    "spread_points", "avg_spread_points", "swap_long",
                    "suggested_stop_pips", "suggested_tp_pips",
                    "suggested_sl_price_buy", "value_per_point"):
            self.assertIn(key, self.row)
        self.assertGreater(self.row["atr_h1_pips"], 0)
        self.assertLessEqual(self.row["suggested_sl_price_buy"], self.row["price"])

    def test_pips_are_in_symbol_units(self):
        self.assertAlmostEqual(self.row["pip"], 0.0001)
        self.assertGreater(self.row["suggested_stop_pips"], 0)
        self.assertAlmostEqual(self.row["suggested_tp_pips"],
                               self.row["suggested_stop_pips"] * 1.5, places=1)

    def test_write_metrics_file(self):
        code = _load.run(analyst, ["--trader-dir", self.root, "--offline", "--write",
                             "EURUSD", "XAUUSD"])
        self.assertEqual(code, 0)
        data = _load.read_json(os.path.join(self.root, "metrics.json"))
        self.assertEqual(sorted(data["symbols"]), ["EURUSD", "XAUUSD"])
        self.assertEqual(data["mode"], "offline")


class TestScreener(unittest.TestCase):
    def row(self, **over):
        base = {"symbol": "EURUSD", "price": 1.08, "atr_h1_pips": 12.0, "adr20_pips": 70.0,
                "spread_points": 8, "avg_spread_points": 9, "trend_d1": "up",
                "trend_h1": "up", "rsi_h1": 58.0, "swap_long": -6.0, "swap_short": 1.5,
                "ema_slope_d1_pct": 0.4, "suggested_stop_pips": 18.0,
                "suggested_tp_pips": 36.0}
        base.update(over)
        return base

    def test_clean_row_passes(self):
        fails, notes, side, score, rr = screen.check_symbol(self.row(), screen.DEFAULT_RULES)
        self.assertEqual(fails, [])
        self.assertEqual(side, "buy")
        self.assertGreater(score["trend_strength"], 0)

    def test_tight_atr_fails(self):
        fails, _, _, _, _ = screen.check_symbol(self.row(atr_h1_pips=2.0),
                                                dict(screen.DEFAULT_RULES, min_atr_pips=8))
        self.assertTrue(any("ATR" in f for f in fails))

    def test_wide_spread_fails(self):
        fails, _, _, _, _ = screen.check_symbol(
            self.row(spread_points=40), dict(screen.DEFAULT_RULES, max_spread_points=20))
        self.assertTrue(any("spread" in f for f in fails))

    def test_spread_to_atr_fails(self):
        fails, _, _, _, _ = screen.check_symbol(
            self.row(spread_points=30, atr_h1_pips=10.0),
            dict(screen.DEFAULT_RULES, max_spread_to_atr=0.1))
        self.assertTrue(any("ATR" in f for f in fails))

    def test_trend_filter(self):
        fails, _, side, _, _ = screen.check_symbol(self.row(trend_d1="down"),
                                                   dict(screen.DEFAULT_RULES, trend="up"))
        self.assertTrue(any("trend" in f for f in fails))
        self.assertIsNone(side)

    def test_down_trend_gives_sell(self):
        _, _, side, _, _ = screen.check_symbol(
            self.row(trend_d1="down"), dict(screen.DEFAULT_RULES, sides="trend"))
        self.assertEqual(side, "sell")

    def test_reward_risk_filter(self):
        fails, _, _, _, _ = screen.check_symbol(
            self.row(suggested_stop_pips=20.0, suggested_tp_pips=20.0),
            dict(screen.DEFAULT_RULES, min_reward_risk=2.0))
        self.assertTrue(any("reward:risk" in f for f in fails))

    def test_swap_filter(self):
        fails, _, _, _, _ = screen.check_symbol(
            self.row(swap_long=-80.0), dict(screen.DEFAULT_RULES, max_swap_per_lot=40))
        self.assertTrue(any("swap" in f for f in fails))

    def test_screen_end_to_end_writes_targets(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            _load.run(analyst, ["--trader-dir", root, "--offline", "--write"])
            _load.write_json(os.path.join(root, "rules.json"),
                             dict(screen.DEFAULT_RULES, min_atr_pips=0, max_spread_points=60,
                                  min_adr_pips=0, sides="both", top=2))
            code = _load.run(screen, [os.path.join(root, "metrics.json"),
                                "--rules", os.path.join(root, "rules.json"),
                                "--write-targets"])
            self.assertEqual(code, 0)
            data = _load.read_json(os.path.join(root, "targets.json"))
            self.assertLessEqual(len(data["targets"]), 2)
            self.assertAlmostEqual(sum(t["weight"] for t in data["targets"]), 100.0, places=1)
            for target in data["targets"]:
                self.assertIn(target["side"], ("buy", "sell"))
        finally:
            _load.cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
