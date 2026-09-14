"""Broker connection module for SikandX.

Supports:
  - MT5  : login + password + server (live or demo), via MetaTrader5 package
  - MT4  : credential capture + guided bridge (no native Python API; runs in
           paper/demo mode until a bridge is configured)
  - REST : generic token-based broker API (base_url + api key + account id)

Security notes:
  - Credentials live only in server memory for the session; never written to disk,
    never logged, never returned by any API route.
  - Live (non-demo) execution additionally requires an explicit one-time
    confirmation (typed CONFIRM LIVE + toggle) enforced at the app layer.
"""
from dataclasses import dataclass, field
import json
import urllib.request
import urllib.error


@dataclass
class BrokerCredentials:
    broker_type: str = "MT5"  # MT5 | MT4 | REST
    login: str = ""
    server: str = ""
    api_key: str = ""
    api_secret: str = ""
    base_url: str = ""
    account_id: str = ""
    is_demo: bool = True
    symbol: str = "XAUUSD"
    # password / token are accepted but held only in memory; excluded from repr
    password: str = field(default="", repr=False)


@dataclass
class AccountSnapshot:
    connected: bool = False
    broker_type: str = "—"
    is_demo: bool = True
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    currency: str = ""
    open_positions: list = field(default_factory=list)  # [{ticket,symbol,side,lots,entry,sl,tp,profit}]
    price: float = 0.0
    source: str = "disconnected"


class BrokerClient:
    """Connected-account facade. Holds no positions itself for live brokers;
    demo/paper positions are tracked by the app's PositionManager."""

    def __init__(self):
        self.creds: BrokerCredentials | None = None
        self.connected = False
        self.last_error = ""
        self._mt5 = None

    # ---------- lifecycle ----------
    def connect(self, creds: BrokerCredentials) -> tuple:
        self.disconnect()
        creds.broker_type = (creds.broker_type or "MT5").upper()
        self.creds = creds
        try:
            if creds.broker_type == "MT5":
                return self._connect_mt5(creds)
            if creds.broker_type == "MT4":
                # No official MT4 Python API — capture intent, stay in supervised demo mode.
                self.connected = True
                self.last_error = ""
                return True, ("MT4 has no native Python API. Credentials accepted and held in memory; "
                              "account runs in supervised demo/paper mode. To enable MT4 live routing, "
                              "attach the SikandX bridge EA to MT4 and set broker type to REST with the bridge URL.")
            if creds.broker_type == "REST":
                return self._connect_rest(creds)
            return False, f"Unknown broker type '{creds.broker_type}'. Choose MT5, MT4 or REST."
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            return False, f"Connection failed: {e}"

    def disconnect(self):
        try:
            if self._mt5 is not None:
                try:
                    self._mt5.shutdown()
                except Exception:
                    pass
        finally:
            self._mt5 = None
            self.connected = False
            # drop secrets from memory
            if self.creds is not None:
                self.creds.password = ""
                self.creds.api_secret = ""
            self.creds = None
            self.last_error = ""

    # ---------- MT5 ----------
    def _connect_mt5(self, creds: BrokerCredentials) -> tuple:
        try:
            import MetaTrader5 as mt5
        except Exception:
            return False, "MetaTrader5 package not installed (Windows + MT5 terminal required). pip install MetaTrader5."
        self._mt5 = mt5
        if not mt5.initialize():
            err = mt5.last_error()
            self._mt5 = None
            return False, f"MT5 initialize() failed: {err}. Open the MT5 terminal and log in at least once."
        login = int(creds.login) if str(creds.login).strip().isdigit() else 0
        if login and (creds.password or creds.server):
            if not mt5.login(login, password=creds.password or "", server=creds.server or ""):
                err = mt5.last_error()
                return False, f"MT5 login failed for {creds.login} @ {creds.server}: {err}."
        info = mt5.account_info()
        if info is None:
            return False, f"MT5 connected but account_info() unavailable: {mt5.last_error()}."
        self.connected = True
        self.last_error = ""
        mode = "demo" if creds.is_demo else "live"
        return True, f"MT5 connected: {info.login} ({info.server}) balance {info.balance:.2f} {info.currency} [{mode}]."

    # ---------- REST ----------
    def _connect_rest(self, creds: BrokerCredentials) -> tuple:
        if not creds.base_url or not creds.api_key or not creds.account_id:
            return False, "REST needs base URL, API key/token and account ID."
        snap, err = self._rest_snapshot(creds)
        if err:
            return False, f"REST connection test failed: {err}"
        self.connected = True
        self.last_error = ""
        mode = "demo" if creds.is_demo else "live"
        return True, f"REST broker connected: account {creds.account_id} equity {snap.equity:.2f} [{mode}]."

    def _rest_headers(self, creds: BrokerCredentials) -> dict:
        h = {"Authorization": f"Bearer {creds.api_key}", "Content-Type": "application/json"}
        if creds.api_secret:
            h["X-API-Secret"] = creds.api_secret
        return h

    def _rest_snapshot(self, creds: BrokerCredentials):
        base = creds.base_url.rstrip("/")
        url = f"{base}/accounts/{creds.account_id}/summary"
        try:
            req = urllib.request.Request(url, headers=self._rest_headers(creds), method="GET")
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            acc = data.get("account", data)
            snap = AccountSnapshot(
                connected=True, broker_type="REST", is_demo=creds.is_demo,
                balance=float(acc.get("balance", 0) or 0),
                equity=float(acc.get("equity", acc.get("balance", 0)) or 0),
                margin=float(acc.get("margin_used", acc.get("margin", 0)) or 0),
                currency=str(acc.get("currency", "")),
                open_positions=list(acc.get("open_positions", acc.get("positions", []) or [])),
                price=float(acc.get("price", 0) or 0), source="rest")
            return snap, ""
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = str(e)
            return None, f"HTTP {e.code}: {detail}"
        except Exception as e:
            return None, str(e)

    # ---------- reads ----------
    def snapshot(self, symbol="XAUUSD") -> AccountSnapshot:
        if not self.connected or self.creds is None:
            return AccountSnapshot()
        try:
            if self.creds.broker_type == "MT5" and self._mt5 is not None:
                mt5 = self._mt5
                info = mt5.account_info()
                if info is None:
                    return AccountSnapshot(connected=True, broker_type="MT5",
                                           is_demo=self.creds.is_demo, source=f"account_info error: {mt5.last_error()}")
                positions = []
                try:
                    poss = mt5.positions_get(symbol=symbol) or mt5.positions_get() or ()
                    for p in poss:
                        positions.append(dict(ticket=p.ticket, symbol=p.symbol,
                                              side="buy" if p.type in (0,) else "sell",
                                              lots=float(p.volume), entry=float(p.price_open),
                                              sl=float(p.sl or 0), tp=float(p.tp or 0),
                                              profit=float(p.profit or 0)))
                except Exception:
                    positions = []
                tick = None
                try:
                    tick = mt5.symbol_info_tick(symbol)
                except Exception:
                    tick = None
                return AccountSnapshot(
                    connected=True, broker_type="MT5", is_demo=self.creds.is_demo,
                    balance=float(info.balance), equity=float(info.equity),
                    margin=float(info.margin or 0), currency=str(info.currency or ""),
                    open_positions=positions,
                    price=float(tick.bid) if tick else 0.0, source="mt5")
            if self.creds.broker_type == "REST":
                snap, err = self._rest_snapshot(self.creds)
                if snap:
                    return snap
                return AccountSnapshot(connected=True, broker_type="REST",
                                       is_demo=self.creds.is_demo, source=f"refresh error: {err}")
            # MT4 supervised demo mode: no live positions to pull
            return AccountSnapshot(connected=True, broker_type=self.creds.broker_type,
                                   is_demo=self.creds.is_demo, source="supervised-demo")
        except Exception as e:
            self.last_error = str(e)
            return AccountSnapshot(connected=True,
                                   broker_type=self.creds.broker_type if self.creds else "?",
                                   is_demo=self.creds.is_demo if self.creds else True,
                                   source=f"refresh error: {e}")

    # ---------- writes ----------
    def place_market_order(self, symbol, side, lots, sl=0.0, tp=0.0, comment="SikandX") -> tuple:
        """Route a market order to the connected account. Demo/paper callers should
        use the app PositionManager instead; this is the live path."""
        if not self.connected or self.creds is None:
            return False, "No broker connected."
        if self.creds.broker_type == "MT5" and self._mt5 is not None:
            return self._mt5_order(symbol, side, lots, sl, tp, comment)
        if self.creds.broker_type == "REST":
            return self._rest_order(symbol, side, lots, sl, tp, comment)
        return False, f"{self.creds.broker_type} order routing is not enabled (supervised demo mode)."

    def _mt5_order(self, symbol, side, lots, sl, tp, comment) -> tuple:
        mt5 = self._mt5
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                # try visible variants
                for cand in [symbol, symbol + "m", symbol + "+", "GOLD"]:
                    info = mt5.symbol_info(cand)
                    if info is not None:
                        symbol = cand
                        break
            if info is None:
                return False, f"Symbol {symbol} not found in MT5."
            if not info.visible:
                mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return False, f"No tick for {symbol}."
            otype = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
            price = tick.ask if side == "buy" else tick.bid
            # filling mode: try IOC then FOK then RETURN
            for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
                req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=float(lots),
                           type=otype, price=float(price), sl=float(sl or 0), tp=float(tp or 0),
                           deviation=30, magic=20260914, comment=comment[:31],
                           type_time=mt5.ORDER_TIME_GTC, type_filling=filling)
                res = mt5.order_send(req)
                if res is None:
                    continue
                if res.retcode == mt5.TRADE_RETCODE_DONE:
                    return True, f"MT5 {side} {lots} {symbol} @ {res.price:.2f} ticket {res.order}."
                # wrong filling mode → retry; otherwise report
                if res.retcode in (10030, 10027):
                    continue
                return False, f"MT5 order rejected retcode={res.retcode} ({res.comment})."
            return False, "MT5 order failed on all filling modes."
        except Exception as e:
            return False, f"MT5 order error: {e}"

    def _rest_order(self, symbol, side, lots, sl, tp, comment) -> tuple:
        base = self.creds.base_url.rstrip("/")
        url = f"{base}/accounts/{self.creds.account_id}/orders"
        payload = json.dumps({"symbol": symbol, "side": side, "lots": lots,
                              "sl": sl, "tp": tp, "type": "market",
                              "comment": comment}).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers=self._rest_headers(self.creds), method="POST")
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            return True, f"REST {side} {lots} {symbol} accepted: {str(data)[:200]}"
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = str(e)
            return False, f"REST order HTTP {e.code}: {detail}"
        except Exception as e:
            return False, f"REST order error: {e}"

    def close_all(self, symbol="XAUUSD") -> tuple:
        if not self.connected or self.creds is None:
            return False, "No broker connected."
        if self.creds.broker_type == "MT5" and self._mt5 is not None:
            mt5 = self._mt5
            try:
                poss = mt5.positions_get(symbol=symbol) or mt5.positions_get() or ()
                if not poss:
                    return True, "No open positions to close."
                n, fails = 0, []
                for p in poss:
                    tick = mt5.symbol_info_tick(p.symbol)
                    if tick is None:
                        fails.append(str(p.ticket))
                        continue
                    otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
                    price = tick.bid if p.type == 0 else tick.ask
                    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
                        req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=p.symbol, volume=float(p.volume),
                                   type=otype, position_id=p.ticket, price=float(price),
                                   deviation=30, magic=20260914, comment="SikandX close",
                                   type_time=mt5.ORDER_TIME_GTC, type_filling=filling)
                        res = mt5.order_send(req)
                        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                            n += 1
                            break
                    else:
                        fails.append(str(p.ticket))
                if fails:
                    return False, f"Closed {n}, failed tickets: {', '.join(fails)}."
                return True, f"Closed {n} position(s)."
            except Exception as e:
                return False, f"MT5 close-all error: {e}"
        if self.creds.broker_type == "REST":
            base = self.creds.base_url.rstrip("/")
            url = f"{base}/accounts/{self.creds.account_id}/positions/close-all"
            try:
                req = urllib.request.Request(url, data=json.dumps({"symbol": symbol}).encode(),
                                             headers=self._rest_headers(self.creds), method="POST")
                with urllib.request.urlopen(req, timeout=12) as r:
                    data = r.read().decode("utf-8", "replace")[:300]
                return True, f"REST close-all accepted: {data}"
            except Exception as e:
                return False, f"REST close-all error: {e}"
        return False, f"{self.creds.broker_type} close-all is not enabled (supervised demo mode)."
