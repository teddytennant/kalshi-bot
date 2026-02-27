"""Tests for strategy ABC and MeanReversionStrategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kalshi_bot.models import (
    Market,
    Orderbook,
    OrderbookLevel,
    OrderType,
    PublicTrade,
    Side,
)
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.strategy import MeanReversionStrategy, Strategy, TradeSignal


@pytest.fixture
def portfolio():
    return Portfolio()


@pytest.fixture
def sample_market():
    return Market(
        ticker="T",
        title="Test",
        status="open",
        result="",
        yes_bid=Decimal("0.65"),
        yes_ask=Decimal("0.67"),
        no_bid=Decimal("0.33"),
        no_ask=Decimal("0.35"),
        volume=1000,
        open_interest=100,
        event_ticker="E",
        series_ticker="S",
        subtitle="",
        close_time="",
    )


@pytest.fixture
def sample_orderbook():
    return Orderbook(
        ticker="T",
        yes=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
        no=tuple([OrderbookLevel(Decimal("0.33"), 120)]),
    )


class TestTradeSignal:
    def test_creation(self):
        sig = TradeSignal(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.65"),
            quantity=10,
        )
        assert sig.ticker == "T"
        assert sig.side == Side.YES
        assert sig.price == Decimal("0.65")

    def test_frozen(self):
        sig = TradeSignal(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.MARKET,
            price=None,
            quantity=5,
        )
        with pytest.raises(AttributeError):
            sig.ticker = "X"


class TestStrategyABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Strategy()

    def test_subclass_must_implement_evaluate(self):
        class BadStrategy(Strategy):
            def select_markets(self, markets):
                return markets

        with pytest.raises(TypeError):
            BadStrategy()


class TestMeanReversionStrategy:
    def test_buy_yes_when_below_mean(self, portfolio, sample_market, sample_orderbook):
        """When current price < avg - threshold, should signal buy YES."""
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        # Recent trades at higher prices -> mean is high, current is low
        trades = [
            _make_trade("T", yes_price=Decimal("0.80")),
            _make_trade("T", yes_price=Decimal("0.78")),
            _make_trade("T", yes_price=Decimal("0.75")),
        ]
        # Current yes_bid is 0.65, mean is ~0.7767, threshold 0.05
        # 0.65 < 0.7767 - 0.05 = 0.7267 -> BUY YES
        signal = strategy.evaluate(sample_market, sample_orderbook, trades, portfolio)
        assert signal is not None
        assert signal.side == Side.YES
        assert signal.quantity == 10

    def test_buy_no_when_above_mean(self, portfolio, sample_orderbook):
        """When current price > avg + threshold, should signal buy NO."""
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        high_market = Market(
            ticker="T",
            title="Test",
            status="open",
            result="",
            yes_bid=Decimal("0.85"),
            yes_ask=Decimal("0.87"),
            no_bid=Decimal("0.13"),
            no_ask=Decimal("0.15"),
            volume=1000,
            open_interest=100,
            event_ticker="E",
            series_ticker="S",
            subtitle="",
            close_time="",
        )
        trades = [
            _make_trade("T", yes_price=Decimal("0.70")),
            _make_trade("T", yes_price=Decimal("0.72")),
            _make_trade("T", yes_price=Decimal("0.68")),
        ]
        # Current yes_bid is 0.85, mean is 0.70, threshold 0.05
        # 0.85 > 0.70 + 0.05 = 0.75 -> BUY NO
        signal = strategy.evaluate(high_market, sample_orderbook, trades, portfolio)
        assert signal is not None
        assert signal.side == Side.NO

    def test_no_signal_within_threshold(self, portfolio, sample_market, sample_orderbook):
        """When price is within threshold of mean, no signal."""
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )
        trades = [
            _make_trade("T", yes_price=Decimal("0.66")),
            _make_trade("T", yes_price=Decimal("0.64")),
            _make_trade("T", yes_price=Decimal("0.65")),
        ]
        # Mean ≈ 0.65, current 0.65, within threshold
        signal = strategy.evaluate(sample_market, sample_orderbook, trades, portfolio)
        assert signal is None

    def test_insufficient_trades(self, portfolio, sample_market, sample_orderbook):
        """Not enough trades to compute mean -> no signal."""
        strategy = MeanReversionStrategy(window=5, threshold=Decimal("0.05"), order_quantity=10)
        trades = [_make_trade("T", yes_price=Decimal("0.70"))]
        signal = strategy.evaluate(sample_market, sample_orderbook, trades, portfolio)
        assert signal is None

    def test_select_markets_filters_open(self):
        strategy = MeanReversionStrategy(window=3, threshold=Decimal("0.05"), order_quantity=10)
        open_market = Market(
            ticker="A", title="A", status="open", result="",
            yes_bid=Decimal("0.50"), yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"), no_ask=Decimal("0.50"),
            volume=100, open_interest=10,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        closed_market = Market(
            ticker="B", title="B", status="closed", result="",
            yes_bid=Decimal("0.50"), yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"), no_ask=Decimal("0.50"),
            volume=100, open_interest=10,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        selected = strategy.select_markets([open_market, closed_market])
        assert len(selected) == 1
        assert selected[0].ticker == "A"

    def test_select_markets_filters_low_volume(self):
        strategy = MeanReversionStrategy(
            window=3,
            threshold=Decimal("0.05"),
            order_quantity=10,
            min_volume=500,
        )
        low_vol = Market(
            ticker="A", title="A", status="open", result="",
            yes_bid=Decimal("0.50"), yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"), no_ask=Decimal("0.50"),
            volume=100, open_interest=10,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        high_vol = Market(
            ticker="B", title="B", status="open", result="",
            yes_bid=Decimal("0.50"), yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"), no_ask=Decimal("0.50"),
            volume=1000, open_interest=10,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        selected = strategy.select_markets([low_vol, high_vol])
        assert len(selected) == 1
        assert selected[0].ticker == "B"


def _make_trade(ticker: str, yes_price: Decimal) -> PublicTrade:
    return PublicTrade(
        ticker=ticker,
        yes_price=yes_price,
        no_price=Decimal("1.00") - yes_price,
        count=1,
        taker_side=Side.YES,
        created_time="2021-01-01T00:00:00Z",
    )
