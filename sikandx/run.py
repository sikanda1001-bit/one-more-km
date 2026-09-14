"""SikandX CLI.

python -m sikandx.run --mode backtest-sample --balance <amount> --target <amount>
python -m sikandx.run --mode backtest-csv --csv path/to/XAUUSD_M1.csv --balance <amount> --target <amount>
python -m sikandx.run --mode fetch --bars 500   (tests MT5 connection)
python -m sikandx.run --mode paper              (paper loop off MT5)
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sikandx.config import SikandXConfig
from sikandx.backtest import run_backtest
from sikandx.sample_data import make_sample_gold_m1
from sikandx.data_mt5 import load_csv, fetch_all_three
from sikandx.paper import run_paper


def main():
    ap = argparse.ArgumentParser(description="SikandX — XAUUSD supply/demand bot")
    ap.add_argument("--mode", default="backtest-sample",
                    choices=["backtest-sample", "backtest-csv", "fetch", "paper"])
    ap.add_argument("--csv", default="")
    ap.add_argument("--balance", type=float, default=100.0)
    ap.add_argument("--target", type=float, default=300.0)
    ap.add_argument("--bars", type=int, default=500)
    ap.add_argument("--max-positions", type=int, default=5)
    args = ap.parse_args()

    cfg = SikandXConfig(start_balance=args.balance, equity_target=args.target,
                        max_total_positions=args.max_positions,
                        max_buys=args.max_positions, max_sells=args.max_positions)

    if args.mode == "backtest-sample":
        df = make_sample_gold_m1()
        res = run_backtest(df, cfg, verbose=True)
        print(f"\nSikandX backtest-sample: trades={res['trades']} wins={res['wins']} "
              f"win_rate={res['win_rate']}% realized=${res['realized']} equity=${res['equity']} "
              f"target=${res['target']} halted={res['halted']} open={res['open']}")
    elif args.mode == "backtest-csv":
        if not args.csv:
            print("pass --csv path/to/XAUUSD_M1.csv")
            return
        df = load_csv(args.csv)
        res = run_backtest(df, cfg, verbose=False)
        print(f"SikandX backtest-csv: trades={res['trades']} win_rate={res['win_rate']}% "
              f"equity=${res['equity']} target=${res['target']} halted={res['halted']}")
    elif args.mode == "fetch":
        data = fetch_all_three(cfg.symbol, args.bars, args.bars, args.bars, cfg.mt5_symbol_variants)
        for k, v in data.items():
            print(f"{k}: {len(v)} bars last_close={v['close'].iloc[-1]:.2f}")
    elif args.mode == "paper":
        run_paper(cfg)


if __name__ == "__main__":
    main()
