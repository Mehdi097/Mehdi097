"""Closed-trade reconstruction and the stats that come out of it."""

import tempfile
import unittest

import _load

journal = _load.load("mt5-journal", "journal")


def deal(position_id, entry, profit, time, symbol="EURUSD", volume=0.1, side=0):
    return {"ticket": position_id * 10 + entry, "position_id": position_id, "symbol": symbol,
            "type": side, "entry": entry, "volume": volume, "price": 1.08,
            "profit": profit, "commission": 0.0, "swap": 0.0, "magic": 7, "time": time}


class TestBuildTrades(unittest.TestCase):
    def test_one_position_two_deals(self):
        deals = [deal(1, 0, 0.0, 1000), deal(1, 1, 25.0, 1600)]
        trades = journal.build_trades(deals)
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades[0]["net"], 25.0)
        self.assertEqual(trades[0]["duration_min"], 10.0)
        self.assertEqual(trades[0]["side"], "buy")

    def test_open_position_is_not_a_trade(self):
        self.assertEqual(journal.build_trades([deal(2, 0, 0.0, 1000)]), [])

    def test_commission_and_swap_count(self):
        deals = [deal(3, 0, 0.0, 1000),
                 {"ticket": 31, "position_id": 3, "symbol": "EURUSD", "type": 1, "entry": 1,
                  "volume": 0.1, "price": 1.09, "profit": 10.0, "commission": -0.7,
                  "swap": -0.3, "magic": 7, "time": 2000}]
        trades = journal.build_trades(deals)
        self.assertAlmostEqual(trades[0]["net"], 9.0)

    def test_partial_close_is_not_counted(self):
        deals = [deal(4, 0, 0.0, 1000, volume=0.2), deal(4, 1, 5.0, 1600, volume=0.1)]
        self.assertEqual(journal.build_trades(deals), [])

    def test_sell_side(self):
        trades = journal.build_trades([deal(5, 0, 0.0, 1000, side=1),
                                       deal(5, 1, -4.0, 2000, side=0)])
        self.assertEqual(trades[0]["side"], "sell")


class TestStats(unittest.TestCase):
    def trades(self, pnls):
        return [{"net": p, "volume": 0.1, "duration_min": 60, "commission": 0.0,
                 "swap": 0.0, "symbol": "EURUSD", "magic": 1, "hour": 10,
                 "weekday": "Mon", "opened": "2026-11-01T10:00:00+00:00",
                 "closed": "2026-11-01T11:00:00+00:00"} for p in pnls]

    def test_basic_math(self):
        stats = journal.stats(self.trades([100, -50, 100, -50, 0]))
        self.assertEqual(stats["trades"], 5)
        self.assertAlmostEqual(stats["net"], 100.0)
        self.assertEqual(stats["wins"], 2)
        self.assertEqual(stats["losses"], 2)
        self.assertEqual(stats["breakeven"], 1)
        self.assertAlmostEqual(stats["win_rate"], 40.0)
        self.assertAlmostEqual(stats["profit_factor"], 2.0)
        self.assertAlmostEqual(stats["expectancy"], 20.0)

    def test_empty(self):
        self.assertEqual(journal.stats([]), {"trades": 0})

    def test_drawdown(self):
        stats = journal.stats(self.trades([100, 100, -250, 100]))
        self.assertAlmostEqual(stats["max_drawdown"], 250.0)

    def test_streaks(self):
        stats = journal.stats(self.trades([-10, -10, -10, 10, 10]))
        self.assertEqual(stats["max_loss_streak"], 3)
        self.assertEqual(stats["max_win_streak"], 2)

    def test_grouping(self):
        trades = self.trades([10, -5, 7])
        grouped = journal.group(trades, "symbol")
        self.assertEqual(grouped["EURUSD"]["trades"], 3)
        self.assertAlmostEqual(grouped["EURUSD"]["net"], 12.0)


class TestJournalOffline(unittest.TestCase):
    def test_reads_the_fixture_history(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            code = _load.run(journal, ["--trader-dir", root, "--offline", "--json", "--trades"])
            self.assertEqual(code, 0)
            b = _load.bridge_for(root)
            trades = journal.build_trades(b.deals())
            stats = journal.stats(trades)
            self.assertEqual(stats["trades"], 8)
            self.assertEqual(sorted(journal.group(trades, "symbol")),
                             ["EURUSD", "GBPUSD", "US30", "USDJPY", "XAUUSD"])
            self.assertGreater(stats["max_drawdown"], 0)
        finally:
            _load.cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
