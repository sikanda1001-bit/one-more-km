"""SikandX config — XAUUSD only, M1/M5/M15, MT5 + backtest/paper first."""
from dataclasses import dataclass, field


@dataclass
class SikandXConfig:
    symbol: str = "XAUUSD"
    # MT5 symbols often look like "XAUUSD", "XAUUSDm", "GOLD" — set yours here
    mt5_symbol_variants: field = field(default_factory=lambda: ["XAUUSD", "XAUUSDm", "XAUUSD+", "GOLD", "XAUUSD.PRO"])

    timeframes: field = field(default_factory=lambda: ["M1", "M5", "M15"])
    primary_tf: str = "M5"  # entries timed on M5, confirmed by M15, triggered by M1

    # --- accounts / targets ---
    start_balance: float = 100.0
    equity_target: float = 300.0  # cap profits: halt new trades once equity >= this
    halt_after_target: bool = True  # stays halted until resume() / told otherwise

    # --- multi-position ---
    max_total_positions: int = 5
    max_buys: int = 5          # multiple buys at once allowed
    max_sells: int = 5
    allow_hedge: bool = True   # buys + sells can coexist
    min_signal_score: int = 45  # 0-100, lower = more trades

    # --- risk (per position) ---
    risk_pct_per_trade: float = 1.0
    sl_atr_mult: float = 1.5
    tp_to_next_zone_mult: float = 1.0  # TP = nearest opposing zone edge
    min_rr: float = 1.5
    spread_points: float = 35.0  # ~$0.35 on gold, adjust to broker
    contract_size: float = 100.0  # 1.0 lot XAUUSD = 100 oz
    stop_level_buffer: float = 0.30  # $0.30 beyond zone edge

    # --- supply / demand detection ---
    swing_window: int = 5
    base_max_bars: int = 8
    base_max_atr_mult: float = 1.0   # base range must be tight vs ATR
    impulse_atr_mult: float = 0.8    # breakout leg must be strong vs ATR
    zone_expiry_bars_m15: int = 300
    zone_touch_tolerance_atr: float = 0.25

    # --- structure ---
    bos_confirm_bars: int = 2
    reversal_wick_ratio: float = 0.45  # pinbar wick / total range

    # --- trendline ---
    trendline_min_touches: int = 3
    trendline_tolerance_atr: float = 0.35
    trendline_lookback: int = 120
