"""Paper trading engine: match orders against real orderbook levels."""

from __future__ import annotations

from decimal import Decimal

from kalshi_bot.client import KalshiClient
from kalshi_bot.models import Fill, Order, OrderType, OrderbookLevel, Side
from kalshi_bot.portfolio import Portfolio


class PaperTradingEngine:
    def __init__(self, portfolio: Portfolio, client: KalshiClient):
        self.portfolio = portfolio
        self.client = client

    def submit_order(self, order: Order) -> list[Fill]:
        if order.quantity <= 0:
            raise ValueError("Quantity must be positive")

        if order.order_type == OrderType.LIMIT and order.price is not None:
            if order.price <= Decimal("0.00") or order.price > Decimal("1.00"):
                raise ValueError("Price must be between 0.01 and 1.00")

        orderbook = self.client.get_orderbook(order.ticker)

        if order.side == Side.YES:
            # Buying YES = lifting the NO side. YES ask = 1 - NO bid.
            levels = self._compute_ask_levels(orderbook.no)
        else:
            # Buying NO = lifting the YES side. NO ask = 1 - YES bid.
            levels = self._compute_ask_levels(orderbook.yes)

        fills = self._match(order, levels)

        if fills:
            total_cost = sum(f.total_cost for f in fills)
            if total_cost > self.portfolio.balance:
                raise ValueError(
                    f"Insufficient balance: need {total_cost}, have {self.portfolio.balance}"
                )

        for fill in fills:
            self.portfolio.record_fill(fill)

        return fills

    def _compute_ask_levels(
        self, bid_levels: tuple[OrderbookLevel, ...]
    ) -> list[OrderbookLevel]:
        """Convert bid levels to ask levels: ask = 1.00 - bid, sorted cheapest first."""
        levels = [
            OrderbookLevel(
                price=Decimal("1.00") - level.price,
                quantity=level.quantity,
            )
            for level in bid_levels
        ]
        levels.sort(key=lambda l: l.price)
        return levels

    def _match(self, order: Order, ask_levels: list[OrderbookLevel]) -> list[Fill]:
        fills: list[Fill] = []
        remaining = order.quantity

        for level in ask_levels:
            if remaining <= 0:
                break

            if order.order_type == OrderType.LIMIT and order.price is not None:
                if level.price > order.price:
                    break

            fill_qty = min(remaining, level.quantity)
            fills.append(
                Fill(
                    ticker=order.ticker,
                    side=order.side,
                    price=level.price,
                    quantity=fill_qty,
                )
            )
            remaining -= fill_qty

        return fills

    def sell_position(self, ticker: str, side: Side, quantity: int) -> list[Fill]:
        """Sell contracts by matching against bid levels.

        Sell YES -> match against orderbook.yes bids (buyers of YES)
        Sell NO  -> match against orderbook.no bids (buyers of NO)
        """
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        position = self.portfolio.get_position(ticker, side)
        if position is None:
            raise ValueError(f"No position for {ticker} {side.value}")
        if quantity > position.quantity:
            raise ValueError(
                f"Sell quantity {quantity} exceeds position {position.quantity}"
            )

        orderbook = self.client.get_orderbook(ticker)

        if side == Side.YES:
            bid_levels = list(orderbook.yes)
        else:
            bid_levels = list(orderbook.no)

        # Bid levels from API are sorted ascending; reverse to sell at best (highest) first
        bid_levels.sort(key=lambda l: l.price, reverse=True)

        fills: list[Fill] = []
        remaining = quantity

        for level in bid_levels:
            if remaining <= 0:
                break
            fill_qty = min(remaining, level.quantity)
            fills.append(
                Fill(
                    ticker=ticker,
                    side=side,
                    price=level.price,
                    quantity=fill_qty,
                )
            )
            remaining -= fill_qty

        for fill in fills:
            self.portfolio.close_position(
                ticker=fill.ticker,
                side=fill.side,
                close_price=fill.price,
                quantity=fill.quantity,
            )

        return fills

    def check_settlements(self, tickers: list[str]) -> None:
        for ticker in tickers:
            market = self.client.get_market(ticker)
            if market.status != "settled":
                continue
            self.portfolio.settle_market(ticker, result=market.result)
