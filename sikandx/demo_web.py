"""SikandX shared demo for Vercel — read-only strategy demo, no live trading.

Differences from the private local bot (sikandx/app.py):
  - No broker connection, no credentials, no order routing, no command execution.
  - Sample-data backtests (capped for serverless timeouts) + sample-feed signals only.
  - Access-code gate: every page requires the shared code (SIKANDX_ACCESS_CODE).
  - Stateless: nothing persists between requests except the signed session cookie.

Vercel entry: api/sikandx.py imports `app` from here.
Local preview: python -m sikandx.demo_web (port 5002).
"""
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, redirect, session

from sikandx.config import SikandXConfig
from sikandx.sample_data import make_sample_gold_m1
from sikandx.backtest import run_backtest
from sikandx.strategy import SikandXStrategy
from sikandx.data_mt5 import resample_m1_to

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_TEMPLATES = os.path.join(HERE, "templates_demo")

DEV_CODE = "sikandx-demo"  # local preview only; production must set SIKANDX_ACCESS_CODE

app = Flask(__name__, template_folder=DEMO_TEMPLATES)
app.secret_key = os.environ.get("SIKANDX_SECRET", "sikandx-demo-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _code_ok(provided: str) -> bool:
    expected = os.environ.get("SIKANDX_ACCESS_CODE", DEV_CODE)
    return hmac.compare_digest(str(provided or ""), str(expected))


@app.before_request
def _gate():
    if request.path.startswith("/static"):
        return None
    if request.endpoint in ("unlock",):
        return None
    if session.get("sikandx_demo_auth") is True:
        return None
    # allow POSTing the code without a session yet
    return render_template("gate.html", error="")


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", cfg=session.get("demo_cfg") or _cfg_defaults(),
                           backtest=None, signal=None, note="")


def _cfg_defaults():
    c = SikandXConfig()
    return {"start_balance": c.start_balance, "equity_target": c.equity_target,
            "max_total_positions": c.max_total_positions, "min_signal_score": c.min_signal_score}


def _cfg_from_form(form):
    d = session.get("demo_cfg") or _cfg_defaults()
    try:
        d["start_balance"] = float(form.get("balance", d["start_balance"]))
    except (ValueError, TypeError):
        pass
    try:
        d["equity_target"] = float(form.get("target", d["equity_target"]))
    except (ValueError, TypeError):
        pass
    try:
        d["max_total_positions"] = max(1, min(10, int(form.get("max_positions", d["max_total_positions"]))))
    except (ValueError, TypeError):
        pass
    try:
        d["min_signal_score"] = max(0, min(100, int(form.get("min_score", d["min_signal_score"]))))
    except (ValueError, TypeError):
        pass
    session["demo_cfg"] = d
    cfg = SikandXConfig(start_balance=d["start_balance"], equity_target=d["equity_target"],
                        max_total_positions=d["max_total_positions"],
                        max_buys=d["max_total_positions"], max_sells=d["max_total_positions"],
                        min_signal_score=d["min_signal_score"])
    return cfg


@app.route("/unlock", methods=["POST"])
def unlock():
    if _code_ok(request.form.get("code", "")):
        session["sikandx_demo_auth"] = True
        session["demo_cfg"] = _cfg_defaults()
        return redirect("/")
    return render_template("gate.html", error="Incorrect access code."), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


@app.route("/backtest", methods=["POST"])
def backtest():
    cfg = _cfg_from_form(request.form)
    try:
        bars = max(300, min(800, int(request.form.get("bars", 600))))
    except (ValueError, TypeError):
        bars = 600
    try:
        res = run_backtest(make_sample_gold_m1(n=bars, seed=7), cfg)
        poss = [dict(id=p.id, side=p.side, entry=round(p.entry, 2), sl=round(p.sl, 2),
                     tp=round(p.tp, 2), lots=p.lots, status=p.status,
                     pnl=round(p.pnl_cash, 2), reason=(p.reason or "")[:120])
                for p in res["positions"][:40]]
        bt = dict(bars=res["bars"], trades=res["trades"], wins=res["wins"],
                  win_rate=res["win_rate"], realized=res["realized"], equity=res["equity"],
                  target=res["target"], halted=res["halted"], open=res["open"],
                  positions=poss, total=len(res["positions"]))
        note = ""
    except Exception as e:
        bt, note = None, f"Backtest failed: {e}"
    return render_template("index.html", cfg=session["demo_cfg"], backtest=bt, signal=None, note=note)


@app.route("/signal", methods=["POST"])
def signal():
    cfg = _cfg_from_form(request.form)
    try:
        df = make_sample_gold_m1(n=600, seed=7)
        m1, m5, m15 = df.tail(400), resample_m1_to(df, "5min").tail(400), resample_m1_to(df, "15min").tail(400)
        sig = SikandXStrategy(cfg).signal(m1, m5, m15)
        bias = sig.get("bias", {})
        s = dict(src="sample feed (shared demo)", price=round(float(m1["close"].iloc[-1]), 2),
                 side=sig.get("side"), score=sig.get("score"),
                 sl=round(sig["sl"], 2) if sig.get("sl") else None,
                 tp=round(sig["tp"], 2) if sig.get("tp") else None,
                 reasons=(sig.get("reasons") or [])[:6],
                 bias_label=bias.get("label") if isinstance(bias, dict) else "?",
                 bias_score=bias.get("score") if isinstance(bias, dict) else 0)
        note = ""
    except Exception as e:
        s, note = None, f"Signal check failed: {e}"
    return render_template("index.html", cfg=session["demo_cfg"], backtest=None, signal=s, note=note)


if __name__ == "__main__":
    app.run(debug=False, port=5002)
