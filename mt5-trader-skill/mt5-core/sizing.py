#!/usr/bin/env python3
"""sizing.py - lot math for MetaTrader 5. Standard library only, no terminal.

Every formula here works from a symbol spec (digits, point, tick size, tick
value, contract size, volume min/max/step, stops level), so it is identical for
EURUSD, XAUUSD, US30, BTCUSD or an exotic pair. That is the whole trick: never
assume 1 lot = 100,000 or 1 pip = $10. Ask the symbol.

    from sizing import volume_for_risk, stops_ok, pip_size
    spec = bridge.spec("EURUSD")
    volume, meta = volume_for_risk(equity=10000, risk_pct=0.5,
                                   sl_distance=0.0020, spec=spec)

Definitions used everywhere in this pack:

  point      the smallest price step MT5 quotes (0.00001 on a 5-digit pair)
  pip        a trader's pip: 10 points on 3- and 5-digit symbols, else 1 point
  tick value money per tick per 1.00 lot, in the account currency
  risk       equity * risk_pct / 100, the most this trade may lose at the stop
  volume     risk / (loss per lot at the stop), rounded DOWN to the lot step
"""

import math

EPS = 1e-9


class SizingError(Exception):
    pass


# ---------------------------------------------------------------- units

def pip_size(spec):
    """A pip in price terms.

    The spec's own `pip` wins when the broker gives one. Otherwise the usual
    convention: 10 points on 1/2/3/5-digit symbols (EURUSD 0.0001, USDJPY 0.01,
    XAUUSD 0.1, US30 1.0), plain points on the rest.
    """
    given = spec.get("pip")
    if isinstance(given, (int, float)) and given > 0:
        return float(given)
    point = float(spec.get("point") or 0.00001)
    digits = int(spec.get("digits", 5))
    return point * 10 if digits in (1, 2, 3, 5) else point


def point_size(spec):
    return float(spec.get("point") or 0.00001)


def pips_to_price(spec, pips):
    return float(pips) * pip_size(spec)


def price_to_pips(spec, distance):
    pip = pip_size(spec)
    return float(distance) / pip if pip else 0.0


def price_to_points(spec, distance):
    point = point_size(spec)
    return float(distance) / point if point else 0.0


def points_to_price(spec, points):
    return float(points) * point_size(spec)


def round_price(spec, price):
    digits = int(spec.get("digits", 5))
    return round(float(price), digits)


# ---------------------------------------------------------------- money per lot

def value_per_point(spec):
    """Account-currency value of one point for 1.00 lot."""
    v = float(spec.get("value_per_point") or 0.0)
    if v > 0:
        return v
    tick_value = float(spec.get("tick_value") or spec.get("tick_value_loss") or 0.0)
    tick_size = float(spec.get("tick_size") or spec.get("point") or 0.0)
    point = point_size(spec)
    if tick_value > 0 and tick_size > 0:
        return tick_value * point / tick_size
    # last resort: assume the profit currency is the account currency
    contract = float(spec.get("contract_size") or 0.0)
    return contract * point if contract > 0 else 0.0


def money_per_pip(spec):
    return value_per_point(spec) * (pip_size(spec) / point_size(spec))


def loss_per_lot(spec, sl_distance):
    """What 1.00 lot loses if price moves sl_distance against you."""
    if sl_distance <= 0:
        raise SizingError("SL distance khass tkoun > 0 / SL distance must be > 0")
    vpp = value_per_point(spec)
    if vpp <= 0:
        raise SizingError("value_per_point = 0: l'symbol ma 3tach tick value / "
                          "symbol gave no tick value, cannot size safely")
    return price_to_points(spec, sl_distance) * vpp


# ---------------------------------------------------------------- volume

def normalise_volume(spec, volume, mode="down"):
    """Clamp to volume_min..volume_max and snap to volume_step."""
    step = float(spec.get("volume_step") or 0.01)
    vmin = float(spec.get("volume_min") or step)
    vmax = float(spec.get("volume_max") or 100.0)
    if step <= 0:
        step = 0.01
    v = float(volume)
    steps = v / step
    if mode == "down":
        snapped = math.floor(steps + EPS) * step
    elif mode == "up":
        snapped = math.ceil(steps - EPS) * step
    else:
        snapped = round(steps) * step
    # kill float dust like 0.30000000000000004
    decimals = max(0, int(round(-math.log10(step))) + 2)
    snapped = round(snapped, decimals)
    clamped = None
    if snapped > vmax:
        snapped, clamped = vmax, "max"
    if snapped < vmin:
        snapped, clamped = vmin, "min"
    snapped = round(snapped, 8)
    return snapped, clamped


def volume_for_risk(equity, risk_pct, sl_distance, spec, *,
                    allow_min_lot=False, max_volume=None):
    """The core sizing call.

    Returns (volume, meta). volume == 0.0 means "do not take this trade":
    even the broker's minimum lot would risk more than you allowed, and this
    function refuses to round up into a bigger loss behind your back.
    """
    if equity is None or float(equity) <= 0:
        raise SizingError("equity khass tkoun > 0 / equity must be > 0")
    if float(risk_pct) <= 0:
        raise SizingError("risk_pct khass ykoun > 0 / risk_pct must be > 0")
    risk_money = float(equity) * float(risk_pct) / 100.0
    per_lot = loss_per_lot(spec, float(sl_distance))
    raw = risk_money / per_lot
    volume, clamped = normalise_volume(spec, raw, "down")
    meta = {
        "equity": round(float(equity), 2),
        "risk_pct": round(float(risk_pct), 4),
        "risk_money": round(risk_money, 2),
        "sl_distance": round(float(sl_distance), 8),
        "sl_pips": round(price_to_pips(spec, sl_distance), 2),
        "sl_points": round(price_to_points(spec, sl_distance), 1),
        "loss_per_lot": round(per_lot, 2),
        "raw_volume": round(raw, 6),
        "volume": volume,
        "actual_risk": round(volume * per_lot, 2),
        "actual_risk_pct": round(volume * per_lot / float(equity) * 100.0, 4),
        "clamped": clamped,
        "min_lot": float(spec.get("volume_min") or 0.01),
        "value_per_point": round(value_per_point(spec), 6),
        "skipped": False,
        "reasons": [],
    }
    if max_volume is not None and volume > float(max_volume):
        volume, _ = normalise_volume(spec, float(max_volume), "down")
        meta["volume"] = volume
        meta["actual_risk"] = round(volume * per_lot, 2)
        meta["actual_risk_pct"] = round(volume * per_lot / float(equity) * 100.0, 4)
        meta["clamped"] = "cap"
        meta["reasons"].append("capped at max_volume %s" % max_volume)
    if raw < float(spec.get("volume_min") or 0.01):
        min_volume = float(spec.get("volume_min") or 0.01)
        min_risk = min_volume * per_lot
        if allow_min_lot:
            volume, _ = normalise_volume(spec, max(raw, min_volume), "up")
            meta.update({"volume": volume, "skipped": False,
                         "actual_risk": round(volume * per_lot, 2),
                         "actual_risk_pct": round(volume * per_lot / float(equity) * 100.0, 4),
                         "clamped": "min"})
            meta["reasons"].append(
                "min lot forced: 3ndak %.2f%% risk instead of %.2f%%" %
                (meta["actual_risk_pct"], float(risk_pct)))
        else:
            meta.update({"volume": 0.0, "skipped": True, "actual_risk": 0.0,
                         "actual_risk_pct": 0.0, "clamped": "min"})
            meta["reasons"].append(
                "SL b3id bzzaf 3la l'risk / stop too wide for %.2f%% of %.2f: "
                "min lot %s = %.2f risk (%.2f%%). Widen the budget or skip." %
                (float(risk_pct), float(equity), min_volume, min_risk,
                 min_risk / float(equity) * 100.0))
    return meta["volume"], meta


def volume_for_cash(cash, spec, price, *, allow_min_lot=False):
    """Size by notional instead of by stop: cash = margin you want to use."""
    contract = float(spec.get("contract_size") or 0.0)
    if contract <= 0 or float(price) <= 0:
        raise SizingError("contract_size / price ghalat / bad contract size or price")
    raw = float(cash) / (contract * float(price))
    volume, clamped = normalise_volume(spec, raw, "down")
    if volume * contract * float(price) < float(cash) * 0.5 and raw < float(spec.get("volume_min") or 0.01):
        if not allow_min_lot:
            return 0.0, {"raw_volume": round(raw, 6), "volume": 0.0, "clamped": "min",
                         "skipped": True, "reasons": ["cash too small for 1 min lot"],
                         "notional": round(volume * contract * float(price), 2)}
    return volume, {"raw_volume": round(raw, 6), "volume": volume, "clamped": clamped,
                    "skipped": False, "reasons": [],
                    "notional": round(volume * contract * float(price), 2)}


# ---------------------------------------------------------------- stops

def stops_ok(spec, side, entry, sl=None, tp=None, spread_points=0):
    """Check SL/TP against the broker's minimum distance (stops level, freeze).

    Returns (ok, issues, sl_distance, tp_distance). For a buy, SL must sit
    below entry and TP above; the reverse for a sell.
    """
    issues = []
    digits = int(spec.get("digits", 5))
    point = point_size(spec)
    min_points = int(spec.get("stops_level_points") or 0) + int(spread_points or 0)
    min_distance = min_points * point
    entry = float(entry)
    sl_distance = abs(entry - float(sl)) if sl is not None else 0.0
    tp_distance = abs(float(tp) - entry) if tp is not None else 0.0

    if sl is not None:
        if side == "buy" and float(sl) >= entry:
            issues.append("buy: SL khass ykoun ta7t l'entry / SL must be below entry")
        if side == "sell" and float(sl) <= entry:
            issues.append("sell: SL khass ykoun fou9 l'entry / SL must be above entry")
        if min_distance and sl_distance < min_distance - EPS:
            issues.append("SL 9rib bzzaf: %.1f points, l'broker bgha >= %d points "
                          "/ stop too close" % (price_to_points(spec, sl_distance), min_points))
        if round(float(sl), digits) != float(sl):
            issues.append("SL 3ndo ktar mn %d digits" % digits)
    elif sl is not None:
        issues.append("SL = 0")

    if tp is not None:
        if side == "buy" and float(tp) <= entry:
            issues.append("buy: TP khass ykoun fou9 l'entry / TP must be above entry")
        if side == "sell" and float(tp) >= entry:
            issues.append("sell: TP khass ykoun ta7t l'entry / TP must be below entry")
        if min_distance and tp_distance and tp_distance < min_distance - EPS:
            issues.append("TP 9rib bzzaf 3la l'broker / TP inside the freeze distance")

    return (not issues), issues, round(sl_distance, 8), round(tp_distance, 8)


def reward_risk(entry, sl, tp):
    """R multiple of the target. None if there is no stop or no target."""
    if sl is None or tp is None:
        return None
    risk = abs(float(entry) - float(sl))
    if risk <= 0:
        return None
    return round(abs(float(tp) - float(entry)) / risk, 2)


def break_even_price(spec, side, entry, commission_per_lot=0.0, swap_per_lot=0.0):
    """Price at which the trade is flat after costs, for 1.00 lot reference."""
    vpp = value_per_point(spec)
    if vpp <= 0:
        return round_price(spec, entry)
    cost_points = (float(commission_per_lot) + float(swap_per_lot)) / vpp
    offset = points_to_price(spec, cost_points)
    return round_price(spec, entry + offset if side == "buy" else entry - offset)


def position_risk(spec, side, entry, sl, volume):
    """Current money at risk for an open position, in account currency."""
    if not sl:
        return None
    distance = abs(float(entry) - float(sl))
    return round(loss_per_lot(spec, distance) * float(volume), 2)
