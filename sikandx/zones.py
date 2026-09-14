"""Supply / Demand zone detection for SikandX (XAUUSD).

Zones = tight base (consolidation) + strong impulse leg.
Types:
  demand (support): Drop-Base-Rally, Rally-Base-Rally
  supply (resistance): Rally-Base-Drop, Drop-Base-Drop
"""
import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def find_swings(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Mark swing highs / lows (vectorized)."""
    out = df.copy()
    h_s = pd.Series(out["high"].to_numpy())
    l_s = pd.Series(out["low"].to_numpy())
    roll_max = h_s.rolling(window * 2 + 1, center=True, min_periods=1).max()
    roll_min = l_s.rolling(window * 2 + 1, center=True, min_periods=1).min()
    sh = (h_s == roll_max).to_numpy()
    sl = (l_s == roll_min).to_numpy()
    # edges don't have a full window — ignore them
    sh[:window] = False
    sh[-window:] = False
    sl[:window] = False
    sl[-window:] = False
    out["swing_high"] = sh
    out["swing_low"] = sl
    return out


def detect_zones(df: pd.DataFrame, swing_window=5, base_max_bars=6,
                 base_max_atr_mult=0.6, impulse_atr_mult=1.2) -> list:
    """Return list of zone dicts: {type, top, bottom, index, score, origin}."""
    if len(df) < 30:
        return []
    a = atr(df).bfill().fillna(0.3)
    zones = []
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    opens = df["open"].to_numpy()
    n = len(df)

    i = 0
    while i < n - 3:
        # try base windows of 2..base_max_bars
        found = None
        for b in range(2, base_max_bars + 1):
            if i + b >= n:
                break
            base_h = highs[i:i + b].max()
            base_l = lows[i:i + b].min()
            base_range = base_h - base_l
            ref_atr = float(a.iloc[i + b]) if float(a.iloc[i + b]) > 0 else 0.3
            if base_range <= base_max_atr_mult * ref_atr:
                # check impulse leg leaving the base
                j = i + b
                # impulse = next 1-3 candles net move
                k_end = min(j + 3, n)
                leg_high = highs[j:k_end].max()
                leg_low = lows[j:k_end].min()
                body_up = leg_high - base_h
                body_dn = base_l - leg_low
                if body_up >= impulse_atr_mult * ref_atr and body_up > body_dn * 1.3:
                    # rally out of base -> demand underneath (or supply flip if came from rally)
                    prev_move = closes[i] - closes[max(0, i - 5)]
                    ztype = "demand"  # Drop-Base-Rally or Rally-Base-Rally both trade as demand
                    top, bottom = base_h, base_l
                    score = min(95, 55 + 20 * (body_up / (ref_atr + 1e-9)) + (5 if prev_move < 0 else 0))
                    found = dict(type=ztype, top=float(top), bottom=float(bottom),
                                 index=int(i), end_index=int(k_end - 1),
                                 score=float(score), origin="rally-base")
                    i = k_end
                    break
                elif body_dn >= impulse_atr_mult * ref_atr and body_dn > body_up * 1.3:
                    ztype = "supply"  # Rally-Base-Drop / Drop-Base-Drop
                    top, bottom = base_h, base_l
                    score = min(95, 55 + 20 * (body_dn / (ref_atr + 1e-9)))
                    found = dict(type=ztype, top=float(top), bottom=float(bottom),
                                 index=int(i), end_index=int(k_end - 1),
                                 score=float(score), origin="drop-base")
                    i = k_end
                    break
        if found:
            zones.append(found)
            continue
        i += 1

    # dedupe overlapping same-side zones: keep highest score
    zones.sort(key=lambda z: z["index"])
    kept = []
    for z in zones:
        if kept and kept[-1]["type"] == z["type"] and not (z["bottom"] > kept[-1]["top"] or z["top"] < kept[-1]["bottom"]):
            if z["score"] > kept[-1]["score"]:
                kept[-1] = z
        else:
            kept.append(z)

    # Fallback: if base-impulse found almost nothing, use recent swing
    # highs/lows as supply/demand so the bot can still trade.
    if len(kept) < 3:
        try:
            sw = find_swings(df, max(3, swing_window - 2))
            ref_atr = float(a.iloc[-1]) if float(a.iloc[-1]) > 0 else 0.3
            half = ref_atr * 0.3
            for idx in sw.index[sw["swing_low"]].tolist()[-4:]:
                px = float(df["low"].iloc[idx])
                kept.append(dict(type="demand", top=px + half, bottom=px - half,
                                 index=int(idx), end_index=int(idx),
                                 score=50.0, origin="swing-fallback"))
            for idx in sw.index[sw["swing_high"]].tolist()[-4:]:
                px = float(df["high"].iloc[idx])
                kept.append(dict(type="supply", top=px + half, bottom=px - half,
                                 index=int(idx), end_index=int(idx),
                                 score=50.0, origin="swing-fallback"))
            kept.sort(key=lambda z: z["index"])
        except Exception:
            pass
    return kept


def zones_near_price(zones: list, price: float, tol: float) -> list:
    """Zones containing price or within tol distance."""
    out = []
    for z in zones:
        if z["bottom"] - tol <= price <= z["top"] + tol:
            out.append(z)
    # nearest first
    out.sort(key=lambda z: abs((z["top"] + z["bottom"]) / 2 - price))
    return out


def nearest_opposing_zone(zones: list, price: float, side: str):
    """For a BUY (side='buy'), target = nearest supply above. For SELL, nearest demand below."""
    if side == "buy":
        cands = [z for z in zones if z["type"] == "supply" and z["bottom"] > price]
        cands.sort(key=lambda z: z["bottom"])
    else:
        cands = [z for z in zones if z["type"] == "demand" and z["top"] < price]
        cands.sort(key=lambda z: -z["top"])
    return cands[0] if cands else None
