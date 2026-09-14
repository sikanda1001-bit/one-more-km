"""SikandX standalone web app — black / gold / white. XAUUSD only.

Run from repo root:
    python -m sikandx.app
Then open http://127.0.0.1:5001/

Connected-account model:
  - /connect stores broker credentials in server memory only (never on disk/logs).
  - Manual chat orders are explicit user overrides and execute with computed SL/TP.
  - Autonomous entries (/auto-trade, auto mode) ONLY execute when the supply/
    demand strategy gate passes: scored zone + BOS-or-trendline confirmation +
    score >= configured minimum. No override unless the rule itself is changed.
  - Live (non-demo) orders require one-time CONFIRM LIVE. Demo/paper never do.
  - Equity target is enforced on every cycle: on breach, close all + halt until resume.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, redirect, jsonify

from sikandx.config import SikandXConfig
from sikandx.sample_data import make_sample_gold_m1
from sikandx.backtest import run_backtest
from sikandx.strategy import SikandXStrategy
from sikandx.positions import PositionManager
from sikandx.broker import BrokerClient, BrokerCredentials
from sikandx.commands import parse_command
from sikandx.data_mt5 import resample_m1_to
from sikandx.zones import atr

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
app.secret_key = os.environ.get("SIKANDX_SECRET", "sikandx-gold-key")

STATE = {
    "cfg": SikandXConfig(),
    "backtest": None,
    "signal": None,
    "note": "",
    "broker": BrokerClient(),
    "broker_msg": "Not connected — validation mode (sample data).",
    "acct": None,
    "paper": PositionManager(SikandXConfig()),
    "paused": False,
    "halted": False,
    "auto": False,
    "live_confirmed": False,
    "chat": [],
}


def _say(role, text):
    STATE["chat"].append({"role": role, "text": str(text)[:600]})
    del STATE["chat"][:-50]


def _update_cfg(form):
    c = STATE["cfg"]
    try:
        c.start_balance = float(form.get("balance", c.start_balance))
    except (ValueError, TypeError):
        pass
    try:
        c.equity_target = float(form.get("target", c.equity_target))
    except (ValueError, TypeError):
        pass
    try:
        n = int(form.get("max_positions", c.max_total_positions))
        c.max_total_positions = max(1, min(20, n))
        c.max_buys = c.max_total_positions
        c.max_sells = c.max_total_positions
    except (ValueError, TypeError):
        pass
    try:
        c.min_signal_score = int(form.get("min_score", c.min_signal_score))
    except (ValueError, TypeError):
        pass
    STATE["paper"].cfg = c
    return c


def _frames(cfg, bars=600):
    """Strategy feed: MT5 terminal candles when available, else synthetic sample."""
    try:
        from sikandx.data_mt5 import fetch_all_three
        d = fetch_all_three(cfg.symbol, bars // 5, bars // 5, bars // 5, cfg.mt5_symbol_variants)
        return d["M1"], d["M5"], d["M15"], "MT5 feed"
    except Exception as e:
        df = make_sample_gold_m1(n=bars, seed=7)
        return (df.tail(400), resample_m1_to(df, "5min").tail(400),
                resample_m1_to(df, "15min").tail(400), f"sample feed (MT5 unavailable: {e})")


def _snapshot():
    b = STATE["broker"]
    if b.connected:
        snap = b.snapshot(STATE["cfg"].symbol)
        STATE["acct"] = snap
        return snap
    return None


def _equity_now(snap, price_fallback=0.0):
    if snap is not None and (snap.equity or snap.balance):
        return float(snap.equity or snap.balance)
    # paper fallback
    px = price_fallback or 0.0
    try:
        return float(STATE["paper"].equity(px)) if px else float(STATE["cfg"].start_balance + STATE["paper"].realized)
    except Exception:
        return float(STATE["cfg"].start_balance)


def _lots_for(equity_base, entry, sl):
    risk_cash = max(equity_base, 0) * (STATE["cfg"].risk_pct_per_trade / 100.0)
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.01
    lots = risk_cash / (dist * STATE["cfg"].contract_size)
    return max(0.01, min(5.0, round(lots, 2)))


def _enforce_target_on_connected() -> tuple:
    """Check equity vs target on the live source of truth. Returns (hit, msg)."""
    cfg = STATE["cfg"]
    snap = _snapshot()
    price = (snap.price if snap and snap.price else 0.0)
    eq = _equity_now(snap, price)
    if eq >= cfg.equity_target:
        STATE["halted"] = True
        b = STATE["broker"]
        if b.connected and (snap and (snap.open_positions or eq >= cfg.equity_target)):
            ok, msg = b.close_all(cfg.symbol)
            STATE["broker_msg"] = msg
        else:
            STATE["paper"].close_all(price or 0.0, reason="EQUITY_TARGET")
        _say("bot", f"Equity target reached ({eq:.2f} >= {cfg.equity_target:.2f}). All positions closed. New entries halted until resume.")
        return True, f"Target reached — closed all, halted ({eq:.2f})."
    return False, ""


def _execute_side(side, lots_req, origin) -> tuple:
    """Execute one side with all persistent gates. Returns (ok, message)."""
    cfg = STATE["cfg"]
    b = STATE["broker"]
    if STATE["paused"]:
        return False, "Blocked: trading is paused. Issue 'resume' first."
    if STATE["halted"]:
        return False, "Blocked: halted at equity target. Issue 'resume' with a new target."
    hit, msg = _enforce_target_on_connected()
    if hit:
        return False, msg

    m1, m5, m15, src = _frames(cfg)
    sig = SikandXStrategy(cfg).signal(m1, m5, m15)
    price = float(m1["close"].iloc[-1])

    if origin == "auto":
        # STRATEGY GATE — no override: scored zone + (BOS or trendline) + min score
        if sig.get("side") != side:
            return False, f"Auto entry refused: strategy shows {sig.get('side')} (need {side})."
        if (sig.get("score") or 0) < cfg.min_signal_score:
            return False, f"Auto entry refused: score {sig.get('score')} < minimum {cfg.min_signal_score}."
        reasons = sig.get("reasons") or []
        has_zone = any("zone" in r for r in reasons)
        has_confirm = any(("BOS" in r or "trendline" in r) for r in reasons)
        if not (has_zone and has_confirm):
            return False, f"Auto entry refused: needs scored zone + BOS/trendline confirmation ({reasons[:3]})."
        sl, tp = float(sig["sl"]), float(sig["tp"])
    else:
        # Manual chat order = explicit user override of direction, still gated on risk/targets.
        if sig.get("side") == side and sig.get("sl") and sig.get("tp"):
            sl, tp = float(sig["sl"]), float(sig["tp"])
        else:
            a = float(atr(m5).bfill().fillna(0.3).iloc[-1] or 0.5)
            if side == "buy":
                sl, tp = price - a * cfg.sl_atr_mult, price + a * cfg.sl_atr_mult * cfg.min_rr
            else:
                sl, tp = price + a * cfg.sl_atr_mult, price - a * cfg.sl_atr_mult * cfg.min_rr

    # max-positions gate (counts live broker positions when connected)
    snap = _snapshot()
    if b.connected and snap is not None and snap.broker_type in ("MT5", "REST"):
        n_open = len([p for p in (snap.open_positions or [])])
        n_side = len([p for p in (snap.open_positions or []) if str(p.get("side", "")).lower() == side])
        if n_open >= cfg.max_total_positions:
            return False, f"Blocked: {n_open} open >= max {cfg.max_total_positions}."
        if side == "buy" and n_side >= cfg.max_buys:
            return False, "Blocked: max buy positions reached."
        if side == "sell" and n_side >= cfg.max_sells:
            return False, "Blocked: max sell positions reached."
        is_live = not (snap.is_demo if snap.is_demo is not None else True)
        if is_live and not STATE["live_confirmed"]:
            return False, "Blocked: live account needs one-time 'CONFIRM LIVE' before any real order."
        lots = float(lots_req) if lots_req else _lots_for(_equity_now(snap, price), price, sl)
        ok, msg = b.place_market_order(cfg.symbol, side, lots, sl, tp, "SikandX " + origin)
        return ok, (msg + f" SL {sl:.2f} TP {tp:.2f} [{src}]") if ok else msg

    # paper / supervised-demo path (MT4 supervised, or no broker)
    pm = STATE["paper"]
    ok, why = pm.can_open(side)
    if not ok:
        return False, f"Blocked: position limit ({why})."
    lots = float(lots_req) if lots_req else pm.lots_for(price, sl)
    pos = pm.open(side, price, sl, tp, 0, f"{origin}|" + "|".join((sig.get("reasons") or [])[:3]))
    if not pos:
        return False, "Order rejected by position manager."
    pos.lots = lots
    if b.connected:
        return True, f"Demo {side} {lots} {cfg.symbol} @ {price:.2f} SL {sl:.2f} TP {tp:.2f} (supervised demo — not routed). [{src}]"
    return True, f"Paper {side} {lots} {cfg.symbol} @ {price:.2f} SL {sl:.2f} TP {tp:.2f}. [{src}]"


def _apply_parsed(p: dict) -> str:
    cfg = STATE["cfg"]
    a = p.get("action")
    if a == "help":
        return p["reply"]
    if a == "empty":
        return p["reply"]
    if a == "unknown" or a == "invalid":
        return p["reply"]
    if a == "status":
        snap = _snapshot()
        if snap and snap.connected:
            return (f"Account [{snap.broker_type}{' demo' if snap.is_demo else ' LIVE'}]: "
                    f"balance {snap.balance:.2f} equity {snap.equity:.2f} "
                    f"open {len(snap.open_positions)} | paused={STATE['paused']} "
                    f"halted={STATE['halted']} auto={STATE['auto']} target={cfg.equity_target:.2f}.")
        eq = _equity_now(None, 0)
        buys, sells, total = STATE["paper"].counts()
        return (f"Validation mode (no broker): paper equity ~{eq:.2f}, open {total} "
                f"(buys {buys}, sells {sells}) | paused={STATE['paused']} halted={STATE['halted']} "
                f"auto={STATE['auto']} target={cfg.equity_target:.2f}.")
    if a == "close_all":
        b = STATE["broker"]
        if b.connected:
            snap = _snapshot()
            if snap and snap.broker_type in ("MT5", "REST"):
                if not snap.is_demo and not STATE["live_confirmed"]:
                    return "Blocked: live account needs 'CONFIRM LIVE' before closing positions."
                ok, msg = b.close_all(cfg.symbol)
                return msg
        m1, _, _, _ = _frames(cfg)
        STATE["paper"].close_all(float(m1["close"].iloc[-1]), reason="chat-close-all")
        return "All paper/demo positions closed."
    if a == "pause":
        STATE["paused"] = True
        STATE["auto"] = False
        return "Trading paused. No new entries will open until 'resume'."
    if a == "resume":
        STATE["paused"] = False
        STATE["halted"] = False
        if p.get("target"):
            cfg.equity_target = float(p["target"])
        return f"Resumed. Target {cfg.equity_target:.2f} active and enforced on every cycle."
    if a == "set_target":
        cfg.equity_target = float(p["target"])
        STATE["halted"] = False
        return f"Equity target set to {cfg.equity_target:.2f} and persisted for every cycle."
    if a == "set_max_positions":
        v = max(1, min(20, int(p["value"])))
        cfg.max_total_positions = cfg.max_buys = cfg.max_sells = v
        return f"Max simultaneous positions set to {v} and persisted."
    if a == "set_min_score":
        cfg.min_signal_score = max(0, min(100, int(p["value"])))
        return f"Minimum signal score set to {cfg.min_signal_score} and persisted."
    if a == "set_risk":
        cfg.risk_pct_per_trade = max(0.1, min(10.0, float(p["value"])))
        return f"Risk per trade set to {cfg.risk_pct_per_trade}% and persisted."
    if a == "set_auto":
        STATE["auto"] = bool(p["value"])
        return p["reply"]
    if a == "confirm_live":
        STATE["live_confirmed"] = True
        return "Live execution authorized (one-time). Real orders are now permitted until 'revoke live'."
    if a == "revoke_live":
        STATE["live_confirmed"] = False
        return "Live authorization revoked. Live orders blocked; demo/paper unaffected."
    if a in ("buy", "sell"):
        ok, msg = _execute_side(a, p.get("lots"), origin="chat")
        return msg
    return "Unhandled command."


@app.route("/", methods=["GET"])
def home():
    snap = _snapshot()
    b = STATE["broker"]
    return render_template(
        "index.html", cfg=STATE["cfg"], backtest=STATE["backtest"], signal=STATE["signal"],
        note=STATE["note"], chat=STATE["chat"][-20:],
        broker_connected=b.connected,
        broker_msg=STATE["broker_msg"],
        broker_type=(b.creds.broker_type if b.creds else "—"),
        broker_demo=(b.creds.is_demo if b.creds else True),
        acct=snap, paused=STATE["paused"], halted=STATE["halted"], auto=STATE["auto"],
        live_confirmed=STATE["live_confirmed"])


@app.route("/backtest", methods=["POST"])
def backtest():
    cfg = _update_cfg(request.form)
    try:
        bars = max(500, min(4000, int(request.form.get("bars", 1500))))
    except (ValueError, TypeError):
        bars = 1500
    STATE["note"] = ""
    try:
        res = run_backtest(make_sample_gold_m1(n=bars), cfg)
        poss = [dict(id=p.id, side=p.side, entry=round(p.entry, 2), sl=round(p.sl, 2),
                     tp=round(p.tp, 2), lots=p.lots, status=p.status,
                     pnl=round(p.pnl_cash, 2), reason=(p.reason or "")[:120])
                for p in res["positions"][:60]]
        STATE["backtest"] = dict(bars=res["bars"], trades=res["trades"], wins=res["wins"],
                                 win_rate=res["win_rate"], realized=res["realized"],
                                 equity=res["equity"], target=res["target"],
                                 halted=res["halted"], open=res["open"],
                                 positions=poss, total=len(res["positions"]))
    except Exception as e:
        STATE["note"] = f"Backtest failed: {e}"
        STATE["backtest"] = None
    return redirect("/")


@app.route("/signal", methods=["POST"])
def signal():
    cfg = _update_cfg(request.form)
    STATE["note"] = ""
    try:
        m1, m5, m15, src = _frames(cfg)
        sig = SikandXStrategy(cfg).signal(m1, m5, m15)
        bias = sig.get("bias", {})
        STATE["signal"] = dict(
            src=src, price=round(float(m1["close"].iloc[-1]), 2),
            side=sig.get("side"), score=sig.get("score"),
            sl=round(sig["sl"], 2) if sig.get("sl") else None,
            tp=round(sig["tp"], 2) if sig.get("tp") else None,
            reasons=(sig.get("reasons") or [])[:6],
            bias_label=bias.get("label") if isinstance(bias, dict) else "?",
            bias_score=bias.get("score") if isinstance(bias, dict) else 0)
    except Exception as e:
        STATE["note"] = f"Signal check failed: {e}"
        STATE["signal"] = None
    return redirect("/")


@app.route("/connect", methods=["POST"])
def connect():
    f = request.form
    creds = BrokerCredentials(
        broker_type=f.get("broker_type", "MT5"),
        login=f.get("login", "").strip(),
        password=f.get("password", ""),
        server=f.get("server", "").strip(),
        api_key=f.get("api_key", "").strip(),
        api_secret=f.get("api_secret", ""),
        base_url=f.get("base_url", "").strip(),
        account_id=f.get("account_id", "").strip(),
        is_demo=(f.get("mode", "demo") == "demo"),
        symbol=STATE["cfg"].symbol)
    ok, msg = STATE["broker"].connect(creds)
    STATE["broker_msg"] = msg
    STATE["note"] = "" if ok else msg
    _say("user", f"connect {creds.broker_type} {'demo' if creds.is_demo else 'LIVE'}")
    _say("bot", msg)
    if ok:
        _snapshot()
    return redirect("/")


@app.route("/disconnect", methods=["POST"])
def disconnect():
    STATE["broker"].disconnect()
    STATE["broker_msg"] = "Not connected — validation mode (sample data)."
    STATE["acct"] = None
    _say("bot", "Broker disconnected. Credentials cleared from memory.")
    return redirect("/")


@app.route("/command", methods=["POST"])
def command():
    text = request.form.get("text", "")
    _update_cfg(request.form)
    _say("user", text if text.strip() else "(empty)")
    try:
        p = parse_command(text)
        reply = _apply_parsed(p)
    except Exception as e:
        reply = f"Command failed: {e}"
    _say("bot", reply)
    STATE["note"] = ""
    return redirect("/")


@app.route("/auto-trade", methods=["POST"])
def auto_trade():
    """One autonomous cycle on the connected feed: strategy gate enforced, no override."""
    _update_cfg(request.form)
    if not STATE["auto"]:
        _say("bot", "Auto mode is off. Enable it with 'enable auto' first.")
        return redirect("/")
    cfg = STATE["cfg"]
    try:
        m1, m5, m15, src = _frames(cfg)
        sig = SikandXStrategy(cfg).signal(m1, m5, m15)
        if not sig.get("side"):
            _say("bot", f"Auto scan [{src}]: no qualifying setup ({(sig.get('reasons') or [])[:3]}). No trade.")
            return redirect("/")
        ok, msg = _execute_side(sig["side"], None, origin="auto")
        _say("bot", f"Auto scan [{src}]: {sig['side']} score {sig['score']} — {msg}")
    except Exception as e:
        _say("bot", f"Auto scan failed: {e}")
    return redirect("/")


@app.route("/resume", methods=["POST"])
def resume():
    _update_cfg(request.form)
    STATE["paused"] = False
    STATE["halted"] = False
    STATE["note"] = (f"Resumed — target {STATE['cfg'].equity_target:.2f} active "
                     "and enforced on every cycle.")
    _say("bot", STATE["note"])
    return redirect("/")


@app.route("/confirm-live", methods=["POST"])
def confirm_live():
    typed = (request.form.get("confirm_text", "") or "").strip()
    toggle = request.form.get("live_toggle") == "on"
    if typed == "CONFIRM LIVE" and toggle:
        STATE["live_confirmed"] = True
        _say("bot", "Live execution authorized (one-time). Real orders permitted until revoked.")
    else:
        STATE["note"] = "To authorize live trading, type CONFIRM LIVE and switch the toggle on."
    return redirect("/")


@app.route("/api/status")
def status():
    b, s = STATE["backtest"], STATE["signal"]
    snap = STATE["acct"]
    return jsonify({
        "cfg": {"balance": STATE["cfg"].start_balance, "target": STATE["cfg"].equity_target,
                "max_positions": STATE["cfg"].max_total_positions,
                "min_score": STATE["cfg"].min_signal_score},
        "broker": {"connected": STATE["broker"].connected, "msg": STATE["broker_msg"]},
        "acct": ({"balance": snap.balance, "equity": snap.equity,
                  "open": len(snap.open_positions or [])} if snap and snap.connected else None),
        "flags": {"paused": STATE["paused"], "halted": STATE["halted"],
                  "auto": STATE["auto"], "live_confirmed": STATE["live_confirmed"]},
        "backtest": ({k: b[k] for k in ("trades", "win_rate", "equity", "halted", "open")} if b else None),
        "signal": s,
        "chat": STATE["chat"][-10:]})


if __name__ == "__main__":
    app.run(debug=False, port=5001)
