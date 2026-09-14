"""Market structure for SikandX: BOS/CHoCH, reversals, trendlines."""
import numpy as np
import pandas as pd

from .zones import find_swings, atr


def structure_state(df: pd.DataFrame, swing_window=5, confirm_bars=2) -> dict:
    """Detect trend + last BOS/CHoCH from swing breaks.

    Returns {trend, last_bos_dir, last_bos_index, last_high, last_low, detail}.
    trend in {up, down, range}.
    """
    if len(df) < swing_window * 2 + 10:
        return dict(trend="range", last_bos_dir=None, last_bos_index=None,
                    last_high=None, last_low=None, detail="too-short")
    sw = find_swings(df, swing_window)
    closes = df["close"].to_numpy()
    idx = np.arange(len(df))
    swing_h = idx[sw["swing_high"].to_numpy()]
    swing_l = idx[sw["swing_low"].to_numpy()]
    if len(swing_h) < 2 or len(swing_l) < 2:
        return dict(trend="range", last_bos_dir=None, last_bos_index=None,
                    last_high=None, last_low=None, detail="no-swings")

    last_high = float(df["high"].iloc[swing_h[-1]])
    last_low = float(df["low"].iloc[swing_l[-1]])
    prev_high = float(df["high"].iloc[swing_h[-2]])
    prev_low = float(df["low"].iloc[swing_l[-2]])

    # trend by swing sequence
    if last_high > prev_high and last_low > prev_low:
        trend = "up"
    elif last_high < prev_high and last_low < prev_low:
        trend = "down"
    else:
        trend = "range"

    # BOS: close beyond last swing with confirmation
    last_bos_dir, last_bos_index = None, None
    start = max(swing_h[-1], swing_l[-1])
    for k in range(start, len(df) - confirm_bars + 1):
        window = closes[k:k + confirm_bars]
        if len(window) < confirm_bars:
            break
        if trend in ("up", "range") and np.all(window > last_high):
            last_bos_dir, last_bos_index = "up", int(k + confirm_bars - 1)
            last_high = float(window.max())
        elif trend in ("down", "range") and np.all(window < last_low):
            last_bos_dir, last_bos_index = "down", int(k + confirm_bars - 1)
            last_low = float(window.min())
        # CHoCH: break opposite to trend flips it
        if trend == "up" and np.all(window < last_low):
            trend, last_bos_dir, last_bos_index = "down", "down", int(k + confirm_bars - 1)
        elif trend == "down" and np.all(window > last_high):
            trend, last_bos_dir, last_bos_index = "up", "up", int(k + confirm_bars - 1)

    return dict(trend=trend, last_bos_dir=last_bos_dir, last_bos_index=last_bos_index,
                last_high=last_high, last_low=last_low, detail="ok")


def reversal_signal(df: pd.DataFrame, idx: int, wick_ratio=0.45) -> dict:
    """Price-action reversal at bar idx: pinbar / engulfing / momentum flip.

    Returns {bullish: bool, bearish: bool, kind: str}.
    """
    if idx < 2 or idx >= len(df):
        return dict(bullish=False, bearish=False, kind="none")
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    rng = h[idx] - l[idx]
    if rng <= 0:
        return dict(bullish=False, bearish=False, kind="none")
    body = abs(c[idx] - o[idx])
    upper_wick = h[idx] - max(c[idx], o[idx])
    lower_wick = min(c[idx], o[idx]) - l[idx]

    bullish_pin = lower_wick / rng >= wick_ratio and c[idx] > o[idx]
    bearish_pin = upper_wick / rng >= wick_ratio and c[idx] < o[idx]
    # engulfing vs prior candle
    bull_eng = (c[idx] > o[idx] and c[idx - 1] < o[idx - 1]
                and c[idx] >= o[idx - 1] and o[idx] <= c[idx - 1]
                and body > abs(c[idx - 1] - o[idx - 1]))
    bear_eng = (c[idx] < o[idx] and c[idx - 1] > o[idx - 1]
                and c[idx] <= o[idx - 1] and o[idx] >= c[idx - 1]
                and body > abs(c[idx - 1] - o[idx - 1]))
    # momentum flip: two consecutive closes reverse prior drift
    drift = c[idx - 1] - c[idx - 2]
    bull_flip = drift < 0 and (c[idx] - c[idx - 1]) > abs(drift) * 0.8 and c[idx] > o[idx]
    bear_flip = drift > 0 and (c[idx - 1] - c[idx]) > abs(drift) * 0.8 and c[idx] < o[idx]

    bullish = bool(bullish_pin or bull_eng or bull_flip)
    bearish = bool(bearish_pin or bear_eng or bear_flip)
    kind = "none"
    if bullish and bearish:
        kind = "both"
    elif bullish:
        kind = "pin" if bullish_pin else ("engulf" if bull_eng else "flip")
        kind = "bull-" + kind
    elif bearish:
        kind = "pin" if bearish_pin else ("engulf" if bear_eng else "flip")
        kind = "bear-" + kind
    return dict(bullish=bullish, bearish=bearish, kind=kind)


def detect_trendlines(df: pd.DataFrame, swing_window=5, lookback=120,
                      min_touches=3, tol_atr_mult=0.35) -> list:
    """Fit rising (lows) + falling (highs) trendlines through swings.

    Returns list of {side: support|resistance, slope, intercept(price per bar),
    touches, distance (price - line at last bar), broke: bool}.
    Heuristic, not perfect — best-fit line through last N swing points that
    keeps most bars on one side.
    """
    n = len(df)
    if n < 30:
        return []
    seg = df.iloc[max(0, n - lookback):].reset_index(drop=True)
    m = len(seg)
    a = float(atr(seg).bfill().fillna(0.3).iloc[-1])
    tol = max(a * tol_atr_mult, 1e-9)
    sw = find_swings(seg, swing_window)
    lows_idx = np.where(sw["swing_low"].to_numpy())[0]
    highs_idx = np.where(sw["swing_high"].to_numpy())[0]
    lines = []

    def fit(points_idx, prices, side):
        if len(points_idx) < 2:
            return None
        # try pairs among recent points, count touches
        best = None
        cands = points_idx[-6:]  # limit combos
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                x1, x2 = int(cands[i]), int(cands[j])
                if x2 == x1:
                    continue
                y1, y2 = float(prices[x1]), float(prices[x2])
                slope = (y2 - y1) / (x2 - x1)
                if side == "support" and slope < 0:
                    continue
                if side == "resistance" and slope > 0:
                    continue
                touches = 0
                ok = True
                for k in points_idx:
                    pred = y1 + slope * (int(k) - x1)
                    px = float(prices[k])
                    if abs(px - pred) <= tol * 2:
                        touches += 1
                    # line must not cut through bodies badly
                    if side == "support" and (float(seg["close"].iloc[k]) < pred - tol * 2):
                        ok = False
                        break
                    if side == "resistance" and (float(seg["close"].iloc[k]) > pred + tol * 2):
                        ok = False
                        break
                if ok and touches >= min_touches:
                    # extend to last bar
                    last_pred = y1 + slope * ((m - 1) - x1)
                    last_price = float(seg["close"].iloc[-1])
                    dist = last_price - last_pred
                    score = touches - abs(dist) / (tol + 1e-9) * 0.1
                    if best is None or score > best["score"]:
                        best = dict(side=side, slope=float(slope),
                                    anchor_index=int(x1), anchor_price=y1,
                                    touches=int(touches), distance=float(dist),
                                    line_now=float(last_pred),
                                    broke=bool(dist < -tol if side == "support" else dist > tol),
                                    score=float(score))
        return best

    sup = fit(lows_idx, seg["low"].to_numpy(), "support")
    res = fit(highs_idx, seg["high"].to_numpy(), "resistance")
    if sup:
        lines.append({k: v for k, v in sup.items() if k != "score"})
    if res:
        lines.append({k: v for k, v in res.items() if k != "score"})
    return lines
