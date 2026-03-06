"""Tests for domain models."""

from decimal import Decimal
import pytest

from kalshi_bot.models import (
    Market,
    Orderbook,
    OrderbookLevel,
    PublicTrade,
    Candlestick,
    Order,
    Position,
    Fill,
    Side,
    OrderType,
    OrderStatus,
)


class TestEnums:
    def test_side_values(self):
        assert Side.YES.value == "yes"
        assert Side.NO.value == "no"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.CANCELLED.value == "cancelled"


class TestOrderbookLevel:
    def test_creation(self):
        level = OrderbookLevel(price=Decimal("0.65"), quantity=100)
        assert level.price == Decimal("0.65")
        assert level.quantity == 100

    def test_frozen(self):
        level = OrderbookLevel(price=Decimal("0.65"), quantity=100)
        with pytest.raises(AttributeError):
            level.price = Decimal("0.70")


class TestMarket:
    def test_creation(self):
        market = Market(
            ticker="KXBTC-26FEB21-50000",
            title="Will Bitcoin hit $50,000 by Feb 26?",
            status="open",
            result="",
            yes_bid=Decimal("0.65"),
            yes_ask=Decimal("0.67"),
            no_bid=Decimal("0.33"),
            no_ask=Decimal("0.35"),
            volume=12345,
            open_interest=500,
            event_ticker="KXBTC",
            series_ticker="KXBTC",
            subtitle="Bitcoin price target",
            close_time="2021-02-26T23:59:59Z",
        )
        assert market.ticker == "KXBTC-26FEB21-50000"
        assert market.yes_bid == Decimal("0.65")
        assert market.status == "open"

    def test_frozen(self):
        market = Market(
            ticker="T",
            title="T",
            status="open",
            result="",
            yes_bid=Decimal("0.50"),
            yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"),
            no_ask=Decimal("0.50"),
            volume=0,
            open_interest=0,
            event_ticker="E",
            series_ticker="S",
            subtitle="",
            close_time="",
        )
        with pytest.raises(AttributeError):
            market.ticker = "X"

    def test_from_api(self, sample_market_response):
        market = Market.from_api(sample_market_response)
        assert market.ticker == "KXBTC-26FEB21-50000"
        assert market.yes_bid == Decimal("0.65")
        assert market.yes_ask == Decimal("0.67")
        assert market.no_bid == Decimal("0.33")
        assert market.no_ask == Decimal("0.35")
        assert market.volume == 12345


class TestOrderbook:
    def test_creation(self):
        yes_levels = [OrderbookLevel(Decimal("0.65"), 100)]
        no_levels = [OrderbookLevel(Decimal("0.33"), 120)]
        ob = Orderbook(ticker="T", yes=tuple(yes_levels), no=tuple(no_levels))
        assert len(ob.yes) == 1
        assert len(ob.no) == 1

    def test_from_api(self, sample_orderbook_response):
        ob = Orderbook.from_api("KXBTC-26FEB21-50000", sample_orderbook_response)
        assert ob.ticker == "KXBTC-26FEB21-50000"
        assert len(ob.yes) == 3
        assert ob.yes[0].price == Decimal("0.65")
        assert ob.yes[0].quantity == 100
        assert len(ob.no) == 3
        assert ob.no[0].price == Decimal("0.33")

    def test_best_yes_bid(self, sample_orderbook_response):
        ob = Orderbook.from_api("T", sample_orderbook_response)
        assert ob.best_yes_bid == Decimal("0.65")

    def test_best_no_bid(self, sample_orderbook_response):
        ob = Orderbook.from_api("T", sample_orderbook_response)
        assert ob.best_no_bid == Decimal("0.33")

    def test_yes_ask_from_no_bid(self, sample_orderbook_response):
        ob = Orderbook.from_api("T", sample_orderbook_response)
        # YES ask = 1.00 - best NO bid
        assert ob.yes_ask == Decimal("0.67")

    def test_no_ask_from_yes_bid(self, sample_orderbook_response):
        ob = Orderbook.from_api("T", sample_orderbook_response)
        # NO ask = 1.00 - best YES bid
        assert ob.no_ask == Decimal("0.35")

    def test_empty_orderbook(self):
        ob = Orderbook(ticker="T", yes=(), no=())
        assert ob.best_yes_bid is None
        assert ob.best_no_bid is None
        assert ob.yes_ask is None
        assert ob.no_ask is None


class TestPublicTrade:
    def test_from_api(self):
        data = {
            "ticker": "T",
            "yes_price": 65,
            "no_price": 35,
            "count": 10,
            "taker_side": "yes",
            "created_time": "2021-02-25T10:00:00Z",
        }
        trade = PublicTrade.from_api(data)
        assert trade.ticker == "T"
        assert trade.yes_price == Decimal("0.65")
        assert trade.no_price == Decimal("0.35")
        assert trade.count == 10
        assert trade.taker_side == Side.YES


class TestCandlestick:
    def test_from_api(self):
        data = {
            "ticker": "T",
            "open": 60,
            "high": 68,
            "low": 58,
            "close": 65,
            "volume": 500,
            "start_period_ts": 1614240000,
            "end_period_ts": 1614243600,
        }
        candle = Candlestick.from_api(data)
        assert candle.open == Decimal("0.60")
        assert candle.high == Decimal("0.68")
        assert candle.close == Decimal("0.65")
        assert candle.volume == 500


class TestOrder:
    def test_creation(self):
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.65"),
            quantity=10,
            status=OrderStatus.PENDING,
        )
        assert order.ticker == "T"
        assert order.side == Side.YES
        assert order.price == Decimal("0.65")

    def test_market_order_no_price(self):
        order = Order(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=5,
            status=OrderStatus.PENDING,
        )
        assert order.price is None
        assert order.order_type == OrderType.MARKET


class TestPosition:
    def test_creation(self):
        pos = Position(
            ticker="T",
            side=Side.YES,
            quantity=10,
            avg_price=Decimal("0.65"),
        )
        assert pos.ticker == "T"
        assert pos.quantity == 10

    def test_cost_basis(self):
        pos = Position(
            ticker="T",
            side=Side.YES,
            quantity=10,
            avg_price=Decimal("0.65"),
        )
        assert pos.cost_basis == Decimal("6.50")


class TestFill:
    def test_creation(self):
        fill = Fill(
            ticker="T",
            side=Side.YES,
            price=Decimal("0.65"),
            quantity=10,
        )
        assert fill.ticker == "T"
        assert fill.total_cost == Decimal("6.50")

    def test_frozen(self):
        fill = Fill(
            ticker="T",
            side=Side.YES,
            price=Decimal("0.65"),
            quantity=10,
        )
        with pytest.raises(AttributeError):
            fill.price = Decimal("0.70")
