"""Frozen dataclasses for all domain models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(Enum):
    YES = "yes"
    NO = "no"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


def _cents_to_decimal(cents: int) -> Decimal:
    """Convert Kalshi cent-based price (e.g. 65) to decimal (e.g. 0.65)."""
    return Decimal(cents) / Decimal(100)


@dataclass(frozen=True)
class OrderbookLevel:
    price: Decimal
    quantity: int


@dataclass(frozen=True)
class Market:
    ticker: str
    title: str
    status: str
    result: str
    yes_bid: Decimal
    yes_ask: Decimal
    no_bid: Decimal
    no_ask: Decimal
    volume: int
    open_interest: int
    event_ticker: str
    series_ticker: str
    subtitle: str
    close_time: str

    @classmethod
    def from_api(cls, data: dict) -> Market:
        return cls(
            ticker=data["ticker"],
            title=data["title"],
            status=data["status"],
            result=data.get("result", ""),
            yes_bid=_cents_to_decimal(data.get("yes_bid", 0)),
            yes_ask=_cents_to_decimal(data.get("yes_ask", 0)),
            no_bid=_cents_to_decimal(data.get("no_bid", 0)),
            no_ask=_cents_to_decimal(data.get("no_ask", 0)),
            volume=data.get("volume", 0),
            open_interest=data.get("open_interest", 0),
            event_ticker=data.get("event_ticker", ""),
            series_ticker=data.get("series_ticker", ""),
            subtitle=data.get("subtitle", ""),
            close_time=data.get("close_time", ""),
        )


@dataclass(frozen=True)
class Orderbook:
    ticker: str
    yes: tuple[OrderbookLevel, ...]
    no: tuple[OrderbookLevel, ...]

    @classmethod
    def from_api(cls, ticker: str, data: dict) -> Orderbook:
        ob = data.get("orderbook", data)
        yes_levels = tuple(
            OrderbookLevel(price=_cents_to_decimal(p), quantity=q)
            for p, q in ob.get("yes", [])
        )
        no_levels = tuple(
            OrderbookLevel(price=_cents_to_decimal(p), quantity=q)
            for p, q in ob.get("no", [])
        )
        return cls(ticker=ticker, yes=yes_levels, no=no_levels)

    @property
    def best_yes_bid(self) -> Optional[Decimal]:
        return self.yes[0].price if self.yes else None

    @property
    def best_no_bid(self) -> Optional[Decimal]:
        return self.no[0].price if self.no else None

    @property
    def yes_ask(self) -> Optional[Decimal]:
        if self.best_no_bid is None:
            return None
        return Decimal("1.00") - self.best_no_bid


@dataclass(frozen=True)
class PublicTrade:
    ticker: str
    yes_price: Decimal
    no_price: Decimal
    count: int
    taker_side: Side
    created_time: str

    @classmethod
    def from_api(cls, data: dict) -> PublicTrade:
        return cls(
            ticker=data["ticker"],
            yes_price=_cents_to_decimal(data["yes_price"]),
            no_price=_cents_to_decimal(data["no_price"]),
            count=data["count"],
            taker_side=Side(data["taker_side"]),
            created_time=data["created_time"],
        )


@dataclass(frozen=True)
class Candlestick:
    ticker: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    start_period_ts: int
    end_period_ts: int

    @classmethod
    def from_api(cls, data: dict) -> Candlestick:
        return cls(
            ticker=data["ticker"],
            open=_cents_to_decimal(data["open"]),
            high=_cents_to_decimal(data["high"]),
            low=_cents_to_decimal(data["low"]),
            close=_cents_to_decimal(data["close"]),
            volume=data["volume"],
            start_period_ts=data["start_period_ts"],
            end_period_ts=data["end_period_ts"],
        )


@dataclass(frozen=True)
class Order:
    ticker: str
    side: Side
    order_type: OrderType
    price: Optional[Decimal]
    quantity: int
    status: OrderStatus


@dataclass(frozen=True)
class Position:
    ticker: str
    side: Side
    quantity: int
    avg_price: Decimal

    @property
    def cost_basis(self) -> Decimal:
        return self.avg_price * self.quantity


@dataclass(frozen=True)
class Fill:
    ticker: str
    side: Side
    price: Decimal
    quantity: int

    @property
    def total_cost(self) -> Decimal:
        return self.price * self.quantity
