"""SikandX strategy — supply/demand + BOS + reversals + trendlines, M1/M5/M15."""
import pandas as pd

from .zones import detect_zones, zones_near_price, nearest_opposing_zone, atr
from .structure import structure_state, reversal_signal, detect_trendlines
from .bias import combined_bias


def _frame_signal(df: pd.DataFrame, cfg, bias: dict) -> dict:
    """Single-timeframe setup at last closed bar."""
    if df is None or len(df) < 40:
        return dict(side=None, score=0, reasons=["too-short"])
    i = len(df) - 1
    price = float(df["close"].iloc[i])
    a = float(atr(df).bfill().fillna(0.3).iloc[i])
    tol = a * cfg.zone_touch_tolerance_atr * 2

    zones = detect_zones(df, cfg.swing_window, cfg.base_max_bars,
                         cfg.base_max_atr_mult, cfg.impulse_atr_mult)
    near = zones_near_price(zones, price, tol)
    in_supply = any(z["type"] == "supply" for z in near)
    in_demand = any(z["type"] == "demand" for z in near)
    st = structure_state(df, cfg.swing_window, cfg.bos_confirm_bars)
    rev = reversal_signal(df, i, cfg.reversal_wick_ratio)
    lines = detect_trendlines(df, cfg.swing_window, cfg.trendline_lookback,
                              cfg.trendline_min_touches, cfg.trendline_tolerance_atr)
    sup_bounce = any(L["side"] == "support" and abs(L["distance"]) <= tol * 2 and not L["broke"] for L in lines)
    res_reject = any(L["side"] == "resistance" and abs(L["distance"]) <= tol * 2 and not L["broke"] for L in lines)

    reasons, buy_pts, sell_pts = [], 0, 0

    if in_demand:
        buy_pts += 25
        reasons.append("in-demand-zone")
    if in_supply:
        sell_pts += 25
        reasons.append("in-supply-zone(resistance)")
    if rev["bullish"]:
        buy_pts += 20
        reasons.append(f"bull-rev:{rev['kind']}")
    if rev["bearish"]:
        sell_pts += 20
        reasons.append(f"bear-rev:{rev['kind']}")
    if st["last_bos_dir"] == "up" and st["last_bos_index"] is not None and i - st["last_bos_index"] <= 10:
        buy_pts += 15
        reasons.append("BOS-up")
    if st["last_bos_dir"] == "down" and st["last_bos_index"] is not None and i - st["last_bos_index"] <= 10:
        sell_pts += 15
        reasons.append("BOS-down")
    if st["trend"] == "up":
        buy_pts += 8
    elif st["trend"] == "down":
        sell_pts += 8
    if sup_bounce:
        buy_pts += 10
        reasons.append("trendline-support-bounce")
    if res_reject:
        sell_pts += 10
        reasons.append("trendline-resistance-reject")
    # resistance -> back-to-supply/demand: selling resistance targets demand below
    if in_supply and rev["bearish"]:
        sell_pts += 12
        reasons.append("resistance-reversal-to-demand")
    if in_demand and rev["bullish"]:
        buy_pts += 12
        reasons.append("demand-bounce")

    # bias assist
    if bias["score"] >= 20:
        buy_pts += 8
    elif bias["score"] <= -20:
        sell_pts += 8

    side, score = None, 0
    if buy_pts >= cfg.min_signal_score and buy_pts > sell_pts + 5:
        side, score = "buy", buy_pts
    elif sell_pts >= cfg.min_signal_score and sell_pts > buy_pts + 5:
        side, score = "sell", sell_pts
    return dict(side=side, score=int(score), reasons=reasons, zones=zones, near=near,
                state=st, rev=rev, lines=lines, price=price, atr=a)


class SikandXStrategy:
    def __init__(self, cfg):
        self.cfg = cfg

    def signal(self, m1: pd.DataFrame, m5: pd.DataFrame, m15: pd.DataFrame) -> dict:
        """Multi-TF: M15 bias must agree, M5 setup, M1 trigger refines.

        Returns {side, score, sl, tp, reasons} with SL/TP computed off M5 zones/ATR.
        """
        bias = combined_bias(m1, m5, m15, self.cfg)
        s5 = _frame_signal(m5, self.cfg, bias["M5"] if "M5" in bias else bias)
        s15_trend = (bias["M15"]["trend"] if isinstance(bias.get("M15"), dict) else "range")

        if s5["side"] is None:
            return dict(side=None, score=0, reasons=s5["reasons"], bias=bias, detail=s5)

        # M15 filter: don't buy into M15 supply dominance / downtrend, vice versa
        if s5["side"] == "buy" and (bias["M15"]["score"] <= -35 or s15_trend == "down"):
            return dict(side=None, score=0, reasons=s5["reasons"] + ["vetoed:M15-supply"],
                        bias=bias, detail=s5)
        if s5["side"] == "sell" and (bias["M15"]["score"] >= 35 or s15_trend == "up"):
            return dict(side=None, score=0, reasons=s5["reasons"] + ["vetoed:M15-demand"],
                        bias=bias, detail=s5)

        # M1 trigger: same-direction reversal or BOS boosts score; opposite blocks scalps
        if m1 is not None and len(m1) >= 40:
            t1 = _frame_signal(m1, self.cfg, bias["M1"] if "M1" in bias else bias)
            if t1["side"] == s5["side"]:
                s5["score"] = min(100, s5["score"] + 8)
                s5["reasons"].append("M1-trigger-agrees")
            elif t1["side"] is not None and t1["side"] != s5["side"]:
                return dict(side=None, score=0, reasons=s5["reasons"] + ["vetoed:M1-opposite"],
                            bias=bias, detail=s5)

        price, a = s5["price"], max(s5["atr"], 1e-9)
        zones = s5["zones"]
        if s5["side"] == "buy":
            opp = nearest_opposing_zone(zones, price, "buy")
            tp = float(opp["bottom"]) if opp else price + a * 3.0
            # SL below demand zone or ATR
            dem = [z for z in s5["near"] if z["type"] == "demand"]
            sl = float(min(z["bottom"] for z in dem) - self.cfg.stop_level_buffer) if dem else price - a * self.cfg.sl_atr_mult
            if tp <= price:
                tp = price + a * 2.0
            if sl >= price:
                sl = price - a * self.cfg.sl_atr_mult
        else:
            opp = nearest_opposing_zone(zones, price, "sell")
            tp = float(opp["top"]) if opp else price - a * 3.0
            sup = [z for z in s5["near"] if z["type"] == "supply"]
            sl = float(max(z["top"] for z in sup) + self.cfg.stop_level_buffer) if sup else price + a * self.cfg.sl_atr_mult
            if tp >= price:
                tp = price - a * 2.0
            if sl <= price:
                sl = price + a * self.cfg.sl_atr_mult

        # RR guard
        risk = abs(price - sl)
        reward = abs(tp - price)
        if risk > 0 and reward / risk < self.cfg.min_rr:
            # stretch TP to min RR rather than skip (keeps trade count for multi-position style)
            need = risk * self.cfg.min_rr
            tp = price + need if s5["side"] == "buy" else price - need

        return dict(side=s5["side"], score=s5["score"], sl=float(sl), tp=float(tp),
                    reasons=s5["reasons"], bias=bias, detail=s5)
