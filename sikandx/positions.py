"""Multi-position manager + equity target cap for SikandX."""
from dataclasses import dataclass, field


@dataclass
class Position:
    id: int
    side: str  # 'buy' or 'sell'
    entry: float
    sl: float
    tp: float
    lots: float
    open_index: int
    reason: str = ""
    status: str = "open"
    exit_price: float = 0.0
    pnl_cash: float = 0.0


@dataclass
class PositionManager:
    cfg: object
    balance: float = 100.0
    equity_target: float = 300.0
    positions: list = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""
    _next_id: int = 1
    realized: float = 0.0

    def equity(self, price: float) -> float:
        floating = 0.0
        for p in self.positions:
            if p.status != "open":
                continue
            diff = (price - p.entry) if p.side == "buy" else (p.entry - price)
            floating += diff * p.lots * self.cfg.contract_size
        return self.balance + self.realized + floating

    def target_hit(self, price: float) -> bool:
        return self.equity(price) >= self.equity_target

    def check_target_cap(self, price: float) -> bool:
        """If equity >= target: close all, halt new trades. Returns True if halted."""
        if self.target_hit(price):
            self.close_all(price, reason="EQUITY_TARGET_REACHED")
            if self.cfg.halt_after_target:
                self.halted = True
                self.halt_reason = f"Target ${self.equity_target:.2f} reached — halted until resume()"
            return True
        return False

    def resume(self, new_target: float = None):
        """User tells bot to continue: optionally set a new target."""
        if new_target is not None:
            self.equity_target = float(new_target)
        self.halted = False
        self.halt_reason = ""

    def counts(self):
        buys = sum(1 for p in self.positions if p.status == "open" and p.side == "buy")
        sells = sum(1 for p in self.positions if p.status == "open" and p.side == "sell")
        return buys, sells, buys + sells

    def can_open(self, side: str) -> tuple:
        if self.halted:
            return False, f"halted: {self.halt_reason}"
        buys, sells, total = self.counts()
        if total >= self.cfg.max_total_positions:
            return False, "max_total_positions"
        if side == "buy" and buys >= self.cfg.max_buys:
            return False, "max_buys"
        if side == "sell" and sells >= self.cfg.max_sells:
            return False, "max_sells"
        if not self.cfg.allow_hedge and total > 0:
            first = next((p.side for p in self.positions if p.status == "open"), None)
            if first and first != side:
                return False, "hedge_blocked"
        return True, "ok"

    def lots_for(self, entry: float, sl: float) -> float:
        risk_cash = (self.balance + self.realized) * (self.cfg.risk_pct_per_trade / 100.0)
        dist = abs(entry - sl)
        if dist <= 0:
            return 0.01
        lots = risk_cash / (dist * self.cfg.contract_size)
        # clamp to broker-ish bounds for XAUUSD
        return max(0.01, min(5.0, round(lots, 2)))

    def open(self, side: str, price: float, sl: float, tp: float, index: int, reason="") -> Position | None:
        ok, why = self.can_open(side)
        if not ok:
            return None
        lots = self.lots_for(price, sl)
        # min RR guard
        risk = abs(price - sl)
        reward = abs(tp - price)
        if risk > 0 and reward / risk < self.cfg.min_rr * 0.7:  # soft guard; strategy already filters
            pass
        p = Position(id=self._next_id, side=side, entry=float(price),
                     sl=float(sl), tp=float(tp), lots=lots, open_index=index, reason=reason)
        self._next_id += 1
        self.positions.append(p)
        return p

    def update_bar(self, high: float, low: float, price: float) -> list:
        """Check SL/TP hits intrabar (conservative: SL first). Returns closed list."""
        closed = []
        for p in self.positions:
            if p.status != "open":
                continue
            hit_sl = (low <= p.sl) if p.side == "buy" else (high >= p.sl)
            hit_tp = (high >= p.tp) if p.side == "buy" else (low <= p.tp)
            if hit_sl and hit_tp:
                # ambiguous — assume SL (conservative)
                self._close(p, p.sl)
                closed.append(p)
            elif hit_sl:
                self._close(p, p.sl)
                closed.append(p)
            elif hit_tp:
                self._close(p, p.tp)
                closed.append(p)
        return closed

    def _close(self, p: Position, px: float):
        diff = (px - p.entry) if p.side == "buy" else (p.entry - px)
        p.pnl_cash = diff * p.lots * self.cfg.contract_size
        p.exit_price = float(px)
        p.status = "closed"
        self.realized += p.pnl_cash

    def close_all(self, price: float, reason="manual"):
        for p in self.positions:
            if p.status == "open":
                self._close(p, price)
                p.reason += f"|closed:{reason}"
