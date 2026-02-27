"""Tests for paper trading engine."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kalshi_bot.models import (
    Fill,
    Market,
    Order,
    Orderbook,
    OrderbookLevel,
    OrderStatus,
    OrderType,
    Side,
)
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.engine import PaperTradingEngine


@pytest.fixture
def portfolio():
    return Portfolio(initial_balance=Decimal("10000.00"))


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def engine(portfolio, mock_client):
    return PaperTradingEngine(portfolio=portfolio, client=mock_client)


@pytest.fixture
def sample_orderbook():
    return Orderbook(
        ticker="T",
        yes=tuple([
            OrderbookLevel(price=Decimal("0.65"), quantity=100),
            OrderbookLevel(price=Decimal("0.63"), quantity=200),
            OrderbookLevel(price=Decimal("0.60"), quantity=150),
        ]),
        no=tuple([
            OrderbookLevel(price=Decimal("0.33"), quantity=120),
            OrderbookLevel(price=Decimal("0.30"), quantity=80),
            OrderbookLevel(price=Decimal("0.28"), quantity=200),
        ]),
    )


class TestMarketOrderYes:
    def test_fills_at_ask_price(self, engine, mock_client, sample_orderbook):
        """Buying YES means lifting the NO side (YES ask = 1 - NO bid)."""
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 1
        # YES ask = 1.00 - 0.33 (best NO bid) = 0.67
        assert fills[0].price == Decimal("0.67")
        assert fills[0].quantity == 10
        assert fills[0].side == Side.YES

    def test_walks_multiple_levels(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=150,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        # First 120 at 0.67 (from NO bid 0.33), then 30 at 0.70 (from NO bid 0.30)
        assert len(fills) == 2
        assert fills[0].quantity == 120
        assert fills[0].price == Decimal("0.67")
        assert fills[1].quantity == 30
        assert fills[1].price == Decimal("0.70")


class TestMarketOrderNo:
    def test_fills_at_no_ask(self, engine, mock_client, sample_orderbook):
        """Buying NO means lifting the YES side (NO ask = 1 - YES bid)."""
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.NO,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 1
        # NO ask = 1.00 - 0.65 (best YES bid) = 0.35
        assert fills[0].price == Decimal("0.35")
        assert fills[0].side == Side.NO


class TestLimitOrder:
    def test_limit_yes_fills_within_price(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.67"),
            quantity=200,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        # Only the first NO level at 0.33 gives YES ask 0.67 <= limit 0.67
        assert len(fills) == 1
        assert fills[0].quantity == 120
        assert fills[0].price == Decimal("0.67")

    def test_limit_no_fills_within_price(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.NO,
            order_type=OrderType.LIMIT,
            price=Decimal("0.37"),
            quantity=500,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        # YES bid 0.65 -> NO ask 0.35 <= 0.37, qty 100
        # YES bid 0.63 -> NO ask 0.37 <= 0.37, qty 200
        assert len(fills) == 2
        assert fills[0].price == Decimal("0.35")
        assert fills[0].quantity == 100
        assert fills[1].price == Decimal("0.37")
        assert fills[1].quantity == 200

    def test_limit_no_fill_when_price_too_low(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.50"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 0


class TestValidation:
    def test_insufficient_balance(self, engine, mock_client, sample_orderbook):
        engine.portfolio.balance = Decimal("1.00")
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=100,
            status=OrderStatus.PENDING,
        )
        with pytest.raises(ValueError, match="Insufficient balance"):
            engine.submit_order(order)

    def test_invalid_limit_price_too_high(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("1.01"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        with pytest.raises(ValueError, match="Price must be between"):
            engine.submit_order(order)

    def test_invalid_limit_price_zero(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.00"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        with pytest.raises(ValueError, match="Price must be between"):
            engine.submit_order(order)

    def test_empty_orderbook(self, engine, mock_client):
        mock_client.get_orderbook.return_value = Orderbook(ticker="T", yes=(), no=())
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        fills = engine.submit_order(order)
        assert len(fills) == 0


class TestPortfolioIntegration:
    def test_fill_recorded_in_portfolio(self, engine, mock_client, sample_orderbook):
        mock_client.get_orderbook.return_value = sample_orderbook
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=10,
            status=OrderStatus.PENDING,
        )
        engine.submit_order(order)
        pos = engine.portfolio.get_position("T", Side.YES)
        assert pos is not None
        assert pos.quantity == 10


class TestCheckSettlements:
    def test_settles_resolved_market(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(ticker="T", side=Side.YES, price=Decimal("0.60"), quantity=10)
        )
        settled_market = MagicMock()
        settled_market.ticker = "T"
        settled_market.status = "settled"
        settled_market.result = "yes"
        mock_client.get_market.return_value = settled_market

        engine.check_settlements(["T"])
        assert engine.portfolio.get_position("T", Side.YES) is None
        assert engine.portfolio.realized_pnl == Decimal("4.00")

    def test_skips_open_market(self, engine, mock_client):
        engine.portfolio.record_fill(
            Fill(ticker="T", side=Side.YES, price=Decimal("0.60"), quantity=10)
        )
        open_market = MagicMock()
        open_market.status = "open"
        mock_client.get_market.return_value = open_market

        engine.check_settlements(["T"])
        assert engine.portfolio.get_position("T", Side.YES) is not None
