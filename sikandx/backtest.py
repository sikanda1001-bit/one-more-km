"""Event-driven backtest for SikandX on M1 data (resampled to M5/M15)."""
import pandas as pd

from .strategy import SikandXStrategy
from .positions import PositionManager
from .data_mt5 import resample_m1_to


def run_backtest(df_m1: pd.DataFrame, cfg, verbose=False) -> dict:
    strat = SikandXStrategy(cfg)
    pm = PositionManager(cfg, balance=cfg.start_balance, equity_target=cfg.equity_target)
    # prebuild M5/M15 series; walk M1 bars and use data up to current time
    m5_full = resample_m1_to(df_m1, "5min")
    m15_full = resample_m1_to(df_m1, "15min")
    t5 = m5_full["time"].to_numpy() if "time" in m5_full.columns else None
    t15 = m15_full["time"].to_numpy() if "time" in m15_full.columns else None

    closes_log = []
    warmup = 60  # need enough M5 history for zones/structure
    for i in range(len(df_m1)):
        row = df_m1.iloc[i]
        price, high, low = float(row["close"]), float(row["high"]), float(row["low"])
        # update open positions with this bar
        pm.update_bar(high, low, price)
        if pm.check_target_cap(price):
            if verbose:
                print(f"[TARGET] equity cap hit at bar {i}, equity={pm.equity(price):.2f}")
            break
        if i < warmup or i % 5 != 0:  # decide on M5 boundaries only
            continue
        ts = row["time"] if "time" in df_m1.columns else None
        m1_win = df_m1.iloc[max(0, i - 400):i + 1].reset_index(drop=True)
        if ts is not None and t5 is not None:
            m5_win = m5_full[m5_full["time"] <= ts].tail(400).reset_index(drop=True)
            m15_win = m15_full[m15_full["time"] <= ts].tail(400).reset_index(drop=True)
        else:
            m5_win = m5_full.iloc[:max(10, (i // 5))].tail(400).reset_index(drop=True)
            m15_win = m15_full.iloc[:max(10, (i // 15))].tail(400).reset_index(drop=True)
        if len(m5_win) < 50 or len(m15_win) < 50:
            continue
        sig = strat.signal(m1_win, m5_win, m15_win)
        if sig["side"]:
            pos = pm.open(sig["side"], price, sig["sl"], sig["tp"], i, reason="|".join(sig["reasons"][:4]))
            if verbose and pos:
                print(f"[{i}] {sig['side'].upper()} @{price:.2f} SL={sig['sl']:.2f} TP={sig['tp']:.2f} score={sig['score']} {sig['reasons'][:3]}")
        closes_log.append(pm.equity(price))

    last_px = float(df_m1["close"].iloc[-1])
    pm.check_target_cap(last_px)
    closed = [p for p in pm.positions if p.status == "closed"]
    wins = [p for p in closed if p.pnl_cash > 0]
    eq = pm.equity(last_px)
    return dict(
        bars=len(df_m1), trades=len(closed), wins=len(wins),
        win_rate=round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        realized=round(pm.realized, 2), equity=round(eq, 2),
        target=cfg.equity_target, halted=pm.halted,
        open=sum(1 for p in pm.positions if p.status == "open"),
        positions=pm.positions,
    )
