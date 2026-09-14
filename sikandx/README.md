# SikandX — XAUUSD Supply/Demand Bot

XAUUSD only. M1/M5/M15. MT5 data. Backtest + paper first.

## What it does (your list)
- **XAUUSD only** — `config.symbol`, rejects nothing else by design
- **Multiple positions at once** — `max_total_positions` (default 5), `max_buys`/`max_sells`, hedge allowed, pyramiding multiple buys
- **Supply/demand zones** — tight base + impulse leg (`zones.py`), scored, deduped
- **Supply vs demand meter** — -100..+100 per TF + weighted M1 20% / M5 30% / M15 50% (`bias.py`)
- **Reversals** — pinbar / engulfing / momentum-flip (`structure.reversal_signal`)
- **Break of structure** — swing-high/low breaks + CHoCH trend flip (`structure_state`)
- **Resistance → back to demand** — sells resistance rejections targeting nearest demand zone as TP
- **Trendlines** — support/resistance fit through swings, bounce/break detection
- **Equity target control** — closes all positions and halts new entries once the configured equity target is reached, until a new target is issued

## Honest limit
No bot reads "every fine detail" perfectly or predicts reversals with certainty.
SikandX uses the standard heuristic version of each concept above and exposes scores
so you can tighten `min_signal_score` / filters. Always backtest + paper first.

## Run (no MT5 needed for sample backtest)
```
pip install pandas numpy
python -m sikandx.run --mode backtest-sample --balance <amount> --target <amount>
python -m sikandx.run --mode backtest-csv --csv XAUUSD_M1.csv --balance <amount> --target <amount>
```

## Run with MT5 (Windows + MT5 terminal open, logged in, XAUUSD visible)
```
pip install MetaTrader5 pandas numpy
python -m sikandx.run --mode fetch --bars 500
python -m sikandx.run --mode paper
```

## Target cap behaviour
- equity >= target → `close_all()` + `halted=True`
- bot stays halted until **you** issue a resume command with a new target
- this is enforced in backtest, paper, and connected-account modes

## Safety
Demo/paper modes are the default. Live execution requires explicit one-time
confirmation and is never enabled implicitly.
Trading XAUUSD on leverage is high risk. This is not financial advice.
