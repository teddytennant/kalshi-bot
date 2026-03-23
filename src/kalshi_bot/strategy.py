"""Strategy ABC and MeanReversionStrategy implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from kalshi_bot.models import Market, Orderbook, OrderType, PublicTrade, Side
from kalshi_bot.portfolio import Portfolio


@dataclass(frozen=True)
class TradeSignal:
    ticker: str
    side: Side
    order_type: OrderType
    price: Optional[Decimal]
    quantity: int


class Strategy(ABC):
    @abstractmethod
    def evaluate(
        self,
        market: Market,
        orderbook: Orderbook,
        trades: list[PublicTrade],
        portfolio: Portfolio,
    ) -> Optional[TradeSignal]:
        ...

    @abstractmethod
    def select_markets(self, markets: list[Market]) -> list[Market]:
        ...


class MeanReversionStrategy(Strategy):
    def __init__(
        self,
        window: int = 10,
        threshold: Decimal = Decimal("0.05"),
        order_quantity: int = 10,
        min_volume: int = 0,
        max_spread: Optional[Decimal] = None,
    ):
        self.window = window
        self.threshold = threshold
        self.order_quantity = order_quantity
        self.min_volume = min_volume
        self.max_spread = max_spread

    def evaluate(
        self,
        market: Market,
        orderbook: Orderbook,
        trades: list[PublicTrade],
        portfolio: Portfolio,
    ) -> Optional[TradeSignal]:
        if len(trades) < self.window:
            return None

        recent = trades[: self.window]
        mean_price = sum(t.yes_price for t in recent) / len(recent)
        no_mean = Decimal("1.00") - mean_price

        # Use ask prices for buy signals (what we'd actually pay)
        yes_ask = market.yes_ask
        no_ask = market.no_ask

        if yes_ask > Decimal("0") and yes_ask < mean_price - self.threshold:
            return TradeSignal(
                ticker=market.ticker,
                side=Side.YES,
                order_type=OrderType.LIMIT,
                price=yes_ask,
                quantity=self.order_quantity,
            )
        elif no_ask > Decimal("0") and no_ask < no_mean - self.threshold:
            return TradeSignal(
                ticker=market.ticker,
                side=Side.NO,
                order_type=OrderType.LIMIT,
                price=no_ask,
                quantity=self.order_quantity,
            )

        return None

    def select_markets(self, markets: list[Market]) -> list[Market]:
        selected = []
        for m in markets:
            if m.status not in ("open", "active"):
                continue
            if m.volume < self.min_volume:
                continue
            if self.max_spread is not None:
                spread = m.yes_ask - m.yes_bid
                if spread <= Decimal("0") or spread > self.max_spread:
                    continue
            selected.append(m)
        return selected
