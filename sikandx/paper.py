"""SikandX paper-trading loop (polls MT5, no real orders by default)."""
import time
import pandas as pd

from .strategy import SikandXStrategy
from .positions import PositionManager
from .data_mt5 import fetch_mt5


def run_paper(cfg, poll_seconds=60, live_orders=False, max_iters=None):
    """Paper loop. live_orders=False always (safety) — wire your broker exec here later."""
    strat = SikandXStrategy(cfg)
    pm = PositionManager(cfg, balance=cfg.start_balance, equity_target=cfg.equity_target)
    it = 0
    print(f"SikandX paper started: {cfg.symbol} M1/M5/M15 target=${cfg.equity_target}")
    while True:
        m1 = fetch_mt5(cfg.symbol, "M1", 400, cfg.mt5_symbol_variants)
        m5 = fetch_mt5(cfg.symbol, "M5", 400, cfg.mt5_symbol_variants)
        m15 = fetch_mt5(cfg.symbol, "M15", 400, cfg.mt5_symbol_variants)
        price = float(m1["close"].iloc[-1])
        pm.update_bar(float(m1["high"].iloc[-1]), float(m1["low"].iloc[-1]), price)
        if pm.check_target_cap(price):
            print(f"TARGET HIT equity={pm.equity(price):.2f} — halted until resume()")
            break
        sig = strat.signal(m1, m5, m15)
        if sig["side"]:
            pos = pm.open(sig["side"], price, sig["sl"], sig["tp"], it, "|".join(sig["reasons"][:4]))
            if pos:
                print(f"{sig['side'].upper()} @{price:.2f} SL={sig['sl']:.2f} TP={sig['tp']:.2f} score={sig['score']} {sig['reasons'][:3]} lots={pos.lots}")
                if live_orders:
                    print("!! live_orders requested but not wired — staying paper for safety.")
        else:
            print(f"no-trade px={price:.2f} bias={sig.get('bias', {}).get('label')} reasons={sig.get('reasons', [])[:2]} eq={pm.equity(price):.2f}")
        it += 1
        if max_iters is not None and it >= max_iters:
            break
        time.sleep(poll_seconds)
    return pm
