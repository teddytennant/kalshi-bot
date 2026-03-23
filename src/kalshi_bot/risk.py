"""Risk management: position limits, portfolio allocation, drawdown protection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from kalshi_bot.models import Side
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.strategy import TradeSignal


@dataclass(frozen=True)
class RiskRejection:
    reason: str
    signal: TradeSignal


class RiskManager:
    """Enforces risk constraints before trades are submitted.

    Parameters:
        max_position_size: Max contracts per position (0=unlimited).
        max_positions: Max total open positions (0=unlimited).
        max_portfolio_pct: Max % of initial balance that can be invested (0=unlimited).
        max_loss_pct: Stop trading if portfolio drops below this % of initial (0=disabled).
    """

    def __init__(
        self,
        max_position_size: int = 0,
        max_positions: int = 0,
        max_portfolio_pct: Decimal = Decimal("0"),
        max_loss_pct: Decimal = Decimal("0"),
    ):
        self.max_position_size = max_position_size
        self.max_positions = max_positions
        self.max_portfolio_pct = max_portfolio_pct
        self.max_loss_pct = max_loss_pct

    def check(self, signal: TradeSignal, portfolio: Portfolio) -> Optional[RiskRejection]:
        """Check if a signal passes risk constraints. Returns None if OK, RiskRejection if not."""

        # Drawdown check: stop trading if portfolio has lost too much
        if self.max_loss_pct > 0:
            current_value = portfolio.balance + sum(
                pos.cost_basis for pos in portfolio.positions.values()
            )
            loss_pct = (
                (portfolio.initial_balance - current_value)
                / portfolio.initial_balance
                * 100
            )
            if loss_pct >= self.max_loss_pct:
                return RiskRejection(
                    reason=f"max drawdown exceeded: portfolio down {loss_pct:.1f}% (limit {self.max_loss_pct:.1f}%)",
                    signal=signal,
                )

        # Position count limit
        if self.max_positions > 0:
            if len(portfolio.positions) >= self.max_positions:
                # Allow if we already hold this ticker+side (adding to existing)
                key = (signal.ticker, signal.side)
                if key not in portfolio.positions:
                    return RiskRejection(
                        reason=f"max positions reached: {len(portfolio.positions)}/{self.max_positions}",
                        signal=signal,
                    )

        # Position size limit
        if self.max_position_size > 0:
            existing = portfolio.get_position(signal.ticker, signal.side)
            current_qty = existing.quantity if existing else 0
            if current_qty + signal.quantity > self.max_position_size:
                return RiskRejection(
                    reason=f"position size limit: {current_qty}+{signal.quantity} > {self.max_position_size}",
                    signal=signal,
                )

        # Portfolio allocation limit
        if self.max_portfolio_pct > 0:
            invested = sum(pos.cost_basis for pos in portfolio.positions.values())
            trade_cost = (signal.price or Decimal("0.50")) * signal.quantity
            new_invested = invested + trade_cost
            pct = new_invested / portfolio.initial_balance * 100
            if pct > self.max_portfolio_pct:
                return RiskRejection(
                    reason=f"portfolio allocation limit: {pct:.1f}% > {self.max_portfolio_pct:.1f}%",
                    signal=signal,
                )

        return None
