"""MT5 data layer for SikandX with CSV fallback.

Requires MetaTrader5 package + open MT5 terminal for live fetch.
Backtests work without MT5 by loading CSVs.
"""
import pandas as pd

TF_MAP = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15"}


def _mt5():
    try:
        import MetaTrader5 as mt5
        return mt5
    except Exception:
        return None


def resolve_symbol(mt5, wanted: str, variants: list) -> str | None:
    for s in [wanted] + [v for v in variants if v != wanted]:
        try:
            info = mt5.symbol_info(s)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(s, True)
                return s
        except Exception:
            continue
    return None


def fetch_mt5(symbol: str, timeframe: str, bars: int = 1000, variants=None) -> pd.DataFrame:
    mt5 = _mt5()
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not installed. pip install MetaTrader5 (Windows + MT5 terminal).")
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
    tf_const = getattr(mt5, TF_MAP[timeframe])
    real_symbol = resolve_symbol(mt5, symbol, variants or [])
    if real_symbol is None:
        raise RuntimeError(f"Symbol {symbol} not found in MT5 Market Watch.")
    rates = mt5.copy_rates_from_pos(real_symbol, tf_const, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates for {real_symbol} {timeframe}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["time", "open", "high", "low", "close", "volume"]]


def fetch_all_three(symbol: str, bars_m1=1500, bars_m5=1500, bars_m15=1500, variants=None):
    return {
        "M1": fetch_mt5(symbol, "M1", bars_m1, variants),
        "M5": fetch_mt5(symbol, "M5", bars_m5, variants),
        "M15": fetch_mt5(symbol, "M15", bars_m15, variants),
    }


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    cols = [c.lower() for c in df.columns]
    df.columns = cols
    need = {"open", "high", "low", "close"}
    if not need.issubset(set(df.columns)):
        raise ValueError(f"CSV {path} needs columns {need}, got {list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0
    return df[["time", "open", "high", "low", "close", "volume"]] if "time" in df.columns else df[["open", "high", "low", "close", "volume"]]


def resample_m1_to(df_m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample M1 df to M5/M15 for backtests from a single series."""
    d = df_m1.copy()
    if "time" not in d.columns:
        d["time"] = pd.RangeIndex(len(d))
        d = d.set_index("time")
    else:
        d = d.set_index("time")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = d.resample(rule).agg(agg).dropna().reset_index()
    return out
