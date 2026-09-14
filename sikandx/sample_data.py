"""Synthetic XAUUSD-like M1 data for SikandX tests (no MT5 needed)."""
import numpy as np
import pandas as pd


def make_sample_gold_m1(n=4000, start=2650.0, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # regimes: trend + range + spike (gold-like)
    drift = np.concatenate([
        np.full(n // 4, 0.012),
        np.full(n // 4, -0.010),
        np.zeros(n // 4),
        np.full(n - 3 * (n // 4), 0.008),
    ])
    shocks = rng.normal(0, 0.55, n)
    # occasional impulsive spikes (news)
    spike_idx = rng.choice(n, size=max(5, n // 300), replace=False)
    shocks[spike_idx] += rng.choice([-1, 1], size=len(spike_idx)) * rng.uniform(2.0, 5.0, size=len(spike_idx))
    rets = drift + shocks
    close = start + np.cumsum(rets)
    open_ = np.empty(n)
    open_[0] = start
    open_[1:] = close[:-1]
    spread = np.abs(rng.normal(0.15, 0.08, n))
    high = np.maximum(open_, close) + spread + np.abs(rng.normal(0, 0.12, n))
    low = np.minimum(open_, close) - spread - np.abs(rng.normal(0, 0.12, n))
    times = pd.date_range("2025-01-01", periods=n, freq="min")
    return pd.DataFrame({"time": times, "open": open_, "high": high, "low": low,
                         "close": close, "volume": rng.integers(10, 200, n)})
