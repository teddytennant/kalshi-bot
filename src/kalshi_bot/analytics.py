"""Trade analytics: win rate, drawdown, per-market P&L, trade log."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from kalshi_bot.models import Side


@dataclass(frozen=True)
class TradeRecord:
    """A completed round-trip trade (open + close/settle)."""

    ticker: str
    side: Side
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    pnl: Decimal

    @property
    def pnl_per_contract(self) -> Decimal:
        return self.exit_price - self.entry_price

    @property
    def is_win(self) -> bool:
        return self.pnl > Decimal("0")


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio value for drawdown tracking."""

    cycle: int
    balance: Decimal
    invested: Decimal

    @property
    def total_value(self) -> Decimal:
        return self.balance + self.invested


class Analytics:
    """Tracks trade performance metrics across the session."""

    def __init__(self) -> None:
        self._trades: list[TradeRecord] = []
        self._snapshots: list[PortfolioSnapshot] = []
        self._peak_value: Decimal = Decimal("0")
        self._max_drawdown: Decimal = Decimal("0")

    @property
    def trades(self) -> list[TradeRecord]:
        return list(self._trades)

    @property
    def trade_count(self) -> int:
        return len(self._trades)

    def record_trade(self, trade: TradeRecord) -> None:
        self._trades.append(trade)

    def record_close(
        self,
        ticker: str,
        side: Side,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
    ) -> None:
        pnl = (exit_price - entry_price) * quantity
        self._trades.append(
            TradeRecord(
                ticker=ticker,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                pnl=pnl,
            )
        )

    def record_snapshot(self, cycle: int, balance: Decimal, invested: Decimal) -> None:
        snap = PortfolioSnapshot(cycle=cycle, balance=balance, invested=invested)
        self._snapshots.append(snap)
        total = snap.total_value
        if total > self._peak_value:
            self._peak_value = total
        if self._peak_value > 0:
            dd = (self._peak_value - total) / self._peak_value * 100
            if dd > self._max_drawdown:
                self._max_drawdown = dd

    @property
    def max_drawdown_pct(self) -> Decimal:
        return self._max_drawdown

    @property
    def win_count(self) -> int:
        return sum(1 for t in self._trades if t.is_win)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self._trades if not t.is_win)

    @property
    def win_rate(self) -> Decimal:
        if not self._trades:
            return Decimal("0")
        return Decimal(self.win_count) / Decimal(len(self._trades)) * 100

    @property
    def total_pnl(self) -> Decimal:
        return sum((t.pnl for t in self._trades), Decimal("0"))

    @property
    def avg_win(self) -> Decimal:
        wins = [t.pnl for t in self._trades if t.is_win]
        if not wins:
            return Decimal("0")
        return sum(wins) / len(wins)

    @property
    def avg_loss(self) -> Decimal:
        losses = [t.pnl for t in self._trades if not t.is_win]
        if not losses:
            return Decimal("0")
        return sum(losses) / len(losses)

    @property
    def profit_factor(self) -> Optional[Decimal]:
        """Gross profit / gross loss. None if no losses."""
        gross_profit = sum((t.pnl for t in self._trades if t.is_win), Decimal("0"))
        gross_loss = abs(sum((t.pnl for t in self._trades if not t.is_win), Decimal("0")))
        if gross_loss == 0:
            return None
        return gross_profit / gross_loss

    def per_market_pnl(self) -> dict[str, Decimal]:
        """P&L grouped by ticker."""
        result: dict[str, Decimal] = {}
        for t in self._trades:
            result[t.ticker] = result.get(t.ticker, Decimal("0")) + t.pnl
        return result

    def summary(self) -> dict:
        """Return a summary dict for display or JSON serialization."""
        return {
            "total_trades": self.trade_count,
            "wins": self.win_count,
            "losses": self.loss_count,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_pnl": str(self.total_pnl),
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "profit_factor": str(self.profit_factor) if self.profit_factor is not None else "N/A",
            "max_drawdown": f"{self.max_drawdown_pct:.1f}%",
            "per_market_pnl": {k: str(v) for k, v in self.per_market_pnl().items()},
        }

    def format_report(self) -> str:
        """Format a human-readable performance report."""
        lines = [
            "=" * 50,
            "  TRADE PERFORMANCE REPORT",
            "=" * 50,
        ]

        if not self._trades:
            lines.append("  No completed trades.")
            return "\n".join(lines)

        pnl_sign = "+" if self.total_pnl >= 0 else ""
        lines.extend([
            f"  Total Trades:   {self.trade_count}",
            f"  Wins / Losses:  {self.win_count} / {self.loss_count}",
            f"  Win Rate:       {self.win_rate:.1f}%",
            f"  Total P&L:      {pnl_sign}${self.total_pnl:.2f}",
            f"  Avg Win:        +${self.avg_win:.2f}",
            f"  Avg Loss:       ${self.avg_loss:.2f}",
        ])

        pf = self.profit_factor
        if pf is not None:
            lines.append(f"  Profit Factor:  {pf:.2f}")
        else:
            lines.append(f"  Profit Factor:  N/A (no losses)")

        lines.append(f"  Max Drawdown:   {self.max_drawdown_pct:.1f}%")

        market_pnl = self.per_market_pnl()
        if market_pnl:
            lines.extend(["", "  Per-Market P&L:"])
            for ticker, pnl in sorted(market_pnl.items(), key=lambda x: x[1], reverse=True):
                sign = "+" if pnl >= 0 else ""
                lines.append(f"    {ticker:<30} {sign}${pnl:.2f}")

        lines.append("=" * 50)
        return "\n".join(lines)
