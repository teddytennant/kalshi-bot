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
    ):
        self.window = window
        self.threshold = threshold
        self.order_quantity = order_quantity
        self.min_volume = min_volume

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
        current_price = market.yes_bid

        if current_price < mean_price - self.threshold:
            return TradeSignal(
                ticker=market.ticker,
                side=Side.YES,
                order_type=OrderType.LIMIT,
                price=current_price,
                quantity=self.order_quantity,
            )
        elif current_price > mean_price + self.threshold:
            return TradeSignal(
                ticker=market.ticker,
                side=Side.NO,
                order_type=OrderType.LIMIT,
                price=Decimal("1.00") - current_price,
                quantity=self.order_quantity,
            )

        return None

    def select_markets(self, markets: list[Market]) -> list[Market]:
        return [
            m
            for m in markets
            if m.status == "open" and m.volume >= self.min_volume
        ]
