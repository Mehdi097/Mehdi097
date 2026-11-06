#!/usr/bin/env python3
"""make_fixture.py - build tests/fixtures/snapshot.json deterministically.

The snapshot is what offline mode reads instead of a terminal: one demo
account, five symbols with real-ish specs, H1/D1/M5 bars, two open positions
and a week of closed deals. Run this only when you want to change the fixture.

    python3 tests/make_fixture.py
"""

import datetime
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures", "snapshot.json")

SPECS = {
    "EURUSD": dict(digits=5, point=0.00001, contract=100000, tick_value=1.0, pip=0.0001,
                   base="EUR", quote="USD", start=1.08500, vol=0.00060, spread=8,
                   swap_long=-6.5, swap_short=1.8, stops=0),
    "GBPUSD": dict(digits=5, point=0.00001, contract=100000, tick_value=1.0, pip=0.0001,
                   base="GBP", quote="USD", start=1.27200, vol=0.00080, spread=11,
                   swap_long=-8.2, swap_short=2.1, stops=0),
    "USDJPY": dict(digits=3, point=0.001, contract=100000, tick_value=0.67, pip=0.01,
                   base="USD", quote="JPY", start=152.400, vol=0.090, spread=9,
                   swap_long=6.1, swap_short=-12.4, stops=0),
    "XAUUSD": dict(digits=2, point=0.01, contract=100, tick_value=1.0, pip=0.1,
                   base="XAU", quote="USD", start=3950.00, vol=8.5, spread=22,
                   swap_long=-18.0, swap_short=6.5, stops=30),
    "US30": dict(digits=1, point=0.1, contract=1, tick_value=0.1, pip=1.0,
                 base="USA30", quote="USD", start=47250.0, vol=95.0, spread=24,
                 swap_long=-14.0, swap_short=-3.0, stops=50),
}

DEMO_SPEC_EXTRA = dict(volume_min=0.01, volume_max=100.0, volume_step=0.01,
                       freeze_level_points=0, filling_mode_mask=3, trade_mode=4,
                       currency_margin="USD", margin_initial=0.0)


def bars(rng, start_price, vol, count, step_minutes, start_time, digits):
    out = []
    price = start_price
    t = start_time
    for _ in range(count):
        drift = rng.gauss(0, vol)
        open_ = price
        close = round(open_ + drift, digits)
        high = round(max(open_, close) + abs(rng.gauss(0, vol * 0.6)), digits)
        low = round(min(open_, close) - abs(rng.gauss(0, vol * 0.6)), digits)
        out.append({"time": int(t.timestamp()), "open": open_, "high": high, "low": low,
                    "close": close, "tick_volume": rng.randint(120, 2400),
                    "spread": rng.randint(6, 18), "real_volume": 0})
        price = close
        t += datetime.timedelta(minutes=step_minutes)
    return out


def main():
    rng = random.Random(20261106)
    now = datetime.datetime(2026, 11, 6, 12, 0, tzinfo=datetime.timezone.utc)
    symbols = {}
    for name, s in SPECS.items():
        h1_start = now - datetime.timedelta(hours=320)
        d1_start = now - datetime.timedelta(days=260)
        m5_start = now - datetime.timedelta(hours=10)
        h1 = bars(rng, s["start"], s["vol"], 320, 60, h1_start, s["digits"])
        d1 = bars(rng, s["start"] * 0.94, s["vol"], 260, 1440, d1_start, s["digits"])
        m5 = bars(rng, s["start"], s["vol"] / 3.0, 120, 5, m5_start, s["digits"])
        last = h1[-1]["close"]
        point = s["point"]
        tick = {
            "bid": round(last - s["spread"] * point / 2, s["digits"]),
            "ask": round(last + s["spread"] * point / 2, s["digits"]),
            "last": 0.0, "volume": 42,
            "time": int((now - datetime.timedelta(minutes=2)).timestamp()),
            "time_msc": int((now - datetime.timedelta(minutes=2)).timestamp() * 1000),
            "spread_points": s["spread"],
            "mid": last,
        }
        value_per_point = s["tick_value"] * (point / point)  # one tick == one point here
        spec = dict(DEMO_SPEC_EXTRA)
        spec.update({
            "name": name, "description": name, "path": "Test\\" + name,
            "digits": s["digits"], "point": point, "pip": s["pip"],
            "tick_size": point, "tick_value": s["tick_value"],
            "tick_value_loss": s["tick_value"],
            "value_per_point": value_per_point,
            "contract_size": s["contract"],
            "stops_level_points": s["stops"],
            "spread_points": s["spread"],
            "currency_base": s["base"], "currency_profit": s["quote"],
            "swap_long": s["swap_long"], "swap_short": s["swap_short"],
        })
        symbols[name] = {"spec": spec, "tick": tick,
                         "rates": {"H1": h1, "D1": d1, "M5": m5}}

    positions = [
        {"ticket": 50123456, "symbol": "EURUSD", "type": 0, "volume": 0.05,
         "price_open": 1.08420, "price_current": symbols["EURUSD"]["tick"]["bid"],
         "sl": 1.08100, "tp": 1.09200, "profit": 4.15, "swap": -0.32, "magic": 20261106,
         "comment": "mt5-budget 0.5%",
         "time": int((now - datetime.timedelta(hours=6)).timestamp())},
        {"ticket": 50123499, "symbol": "US30", "type": 1, "volume": 0.20,
         "price_open": 47180.0, "price_current": symbols["US30"]["tick"]["ask"],
         "sl": 47420.0, "tp": 46700.0, "profit": -14.0, "swap": -0.8, "magic": 20261106,
         "comment": "mt5-budget 0.25%",
         "time": int((now - datetime.timedelta(hours=3)).timestamp())},
    ]

    deals = []
    ticket = 60100000
    day = now - datetime.timedelta(days=9)
    plan = [("EURUSD", "buy", 0.10, 1.0820, 1.0864, 9),
            ("GBPUSD", "sell", 0.05, 1.2790, 1.2748, 8),
            ("XAUUSD", "buy", 0.05, 3901.0, 3888.4, 7),
            ("EURUSD", "sell", 0.08, 1.0902, 1.0918, 6),
            ("US30", "buy", 0.10, 47010.0, 47160.0, 5),
            ("USDJPY", "buy", 0.05, 151.90, 152.55, 4),
            ("GBPUSD", "buy", 0.05, 1.2680, 1.2662, 3),
            ("XAUUSD", "sell", 0.04, 3960.0, 3941.0, 2)]
    for sym, side, volume, open_price, close_price, days_ago in plan:
        s = SPECS[sym]
        opened = now - datetime.timedelta(days=days_ago, hours=5)
        closed = opened + datetime.timedelta(hours=3, minutes=20)
        direction = 1 if side == "buy" else -1
        raw = (close_price - open_price) * direction
        profit = round(raw / s["point"] * s["tick_value"] * volume / 1.0, 2)
        if sym == "USDJPY":
            profit = round(raw / 0.001 * 0.67 * volume, 2)
        if sym == "US30":
            profit = round(raw / 0.1 * 0.1 * volume, 2)
        ticket += 1
        deals.append({"ticket": ticket, "position_id": ticket, "symbol": sym,
                      "type": 0 if side == "buy" else 1, "entry": 0,
                      "volume": volume, "price": open_price, "profit": 0.0,
                      "commission": round(-3.5 * volume, 2), "swap": 0.0,
                      "magic": 20261106, "comment": "mt5-budget",
                      "time": int(opened.timestamp())})
        ticket += 1
        deals.append({"ticket": ticket, "position_id": ticket - 1, "symbol": sym,
                      "type": 1 if side == "buy" else 0, "entry": 1,
                      "volume": volume, "price": close_price, "profit": profit,
                      "commission": 0.0, "swap": round(-0.4 * volume, 21),
                      "magic": 20261106, "comment": "tp",
                      "time": int(closed.timestamp())})

    snapshot = {
        "generated": now.isoformat(),
        "mode": "offline",
        "account": {
            "login": 51234567, "name": "Test Demo", "server": "MetaQuotes-Demo",
            "currency": "USD", "balance": 10000.0, "equity": 9989.15,
            "margin": 320.0, "margin_free": 9669.15, "margin_level": 3121.6,
            "profit": -10.85, "leverage": 100, "trade_mode": 0, "margin_mode": 2,
            "trade_allowed": True, "is_real": False,
        },
        "symbols": symbols,
        "positions": positions,
        "orders": [],
        "deals": deals,
        "history_orders": [],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s (%d symbols, %d deals)" % (OUT, len(symbols), len(deals)))


if __name__ == "__main__":
    main()
