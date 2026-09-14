"""Supply vs Demand pressure meter for SikandX."""
import pandas as pd

from .zones import detect_zones, zones_near_price, atr
from .structure import structure_state


def bias_for_frame(df: pd.DataFrame, cfg) -> dict:
    """Score -100 (supply) .. +100 (demand)."""
    if len(df) < 30:
        return dict(score=0, label="BALANCED", trend="range", in_supply=False, in_demand=False)
    zones = detect_zones(df, cfg.swing_window, cfg.base_max_bars,
                         cfg.base_max_atr_mult, cfg.impulse_atr_mult)
    st = structure_state(df, cfg.swing_window, cfg.bos_confirm_bars)
    price = float(df["close"].iloc[-1])
    a = float(atr(df).bfill().fillna(0.3).iloc[-1])
    tol = a * cfg.zone_touch_tolerance_atr

    near = zones_near_price(zones, price, tol * 2)
    in_supply = any(z["type"] == "supply" for z in near)
    in_demand = any(z["type"] == "demand" for z in near)

    score = 0
    # trend component
    if st["trend"] == "up":
        score += 30
    elif st["trend"] == "down":
        score -= 30
    # BOS component
    if st["last_bos_dir"] == "up" and st["last_bos_index"] is not None and len(df) - st["last_bos_index"] < 20:
        score += 20
    elif st["last_bos_dir"] == "down" and st["last_bos_index"] is not None and len(df) - st["last_bos_index"] < 20:
        score -= 20
    # zone interaction
    if in_demand:
        score += 25
    if in_supply:
        score -= 25
    # impulse: last 5 candles body sum
    last5 = df.iloc[-5:]
    bodies = (last5["close"] - last5["open"]).sum()
    score += max(-15, min(15, float(bodies / (a + 1e-9)) * 5))
    # EMA stack
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1] if len(df) >= 50 else ema20
    if ema20 > ema50:
        score += 10
    else:
        score -= 10

    score = max(-100, min(100, int(round(score))))
    label = "DEMAND_DOMINANT" if score >= 20 else ("SUPPLY_DOMINANT" if score <= -20 else "BALANCED")
    return dict(score=score, label=label, trend=st["trend"], in_supply=in_supply,
                in_demand=in_demand, bos=st["last_bos_dir"], zones=len(zones))


def combined_bias(m1: pd.DataFrame, m5: pd.DataFrame, m15: pd.DataFrame, cfg) -> dict:
    b1 = bias_for_frame(m1, cfg) if m1 is not None and len(m1) else dict(score=0, label="BALANCED")
    b5 = bias_for_frame(m5, cfg) if m5 is not None and len(m5) else dict(score=0, label="BALANCED")
    b15 = bias_for_frame(m15, cfg) if m15 is not None and len(m15) else dict(score=0, label="BALANCED")
    # M15 heaviest: M1 20% / M5 30% / M15 50%
    score = int(round(b1["score"] * 0.2 + b5["score"] * 0.3 + b15["score"] * 0.5))
    label = "DEMAND_DOMINANT" if score >= 20 else ("SUPPLY_DOMINANT" if score <= -20 else "BALANCED")
    return dict(score=score, label=label, M1=b1, M5=b5, M15=b15)
