"""Tests for RiskManager."""

from decimal import Decimal

import pytest

from kalshi_bot.models import Fill, OrderType, Side
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.risk import RiskManager, RiskRejection
from kalshi_bot.strategy import TradeSignal


def _signal(ticker="T", side=Side.YES, price=Decimal("0.50"), qty=10):
    return TradeSignal(
        ticker=ticker, side=side, order_type=OrderType.LIMIT,
        price=price, quantity=qty,
    )


def _fill(ticker="T", side=Side.YES, price=Decimal("0.50"), qty=10):
    return Fill(ticker=ticker, side=side, price=price, quantity=qty)


class TestMaxPositionSize:
    def test_allows_within_limit(self):
        rm = RiskManager(max_position_size=100)
        portfolio = Portfolio()
        result = rm.check(_signal(qty=50), portfolio)
        assert result is None

    def test_rejects_exceeding_limit(self):
        rm = RiskManager(max_position_size=20)
        portfolio = Portfolio()
        result = rm.check(_signal(qty=25), portfolio)
        assert result is not None
        assert "position size limit" in result.reason

    def test_accounts_for_existing_position(self):
        rm = RiskManager(max_position_size=30)
        portfolio = Portfolio()
        portfolio.record_fill(_fill(qty=25))
        result = rm.check(_signal(qty=10), portfolio)
        assert result is not None
        assert "position size limit" in result.reason

    def test_allows_adding_to_existing_within_limit(self):
        rm = RiskManager(max_position_size=30)
        portfolio = Portfolio()
        portfolio.record_fill(_fill(qty=15))
        result = rm.check(_signal(qty=10), portfolio)
        assert result is None

    def test_disabled_when_zero(self):
        rm = RiskManager(max_position_size=0)
        portfolio = Portfolio()
        result = rm.check(_signal(qty=10000), portfolio)
        assert result is None


class TestMaxPositions:
    def test_allows_within_limit(self):
        rm = RiskManager(max_positions=5)
        portfolio = Portfolio()
        portfolio.record_fill(_fill(ticker="A", price=Decimal("0.10")))
        result = rm.check(_signal(ticker="B"), portfolio)
        assert result is None

    def test_rejects_when_at_limit(self):
        rm = RiskManager(max_positions=2)
        portfolio = Portfolio()
        portfolio.record_fill(_fill(ticker="A", price=Decimal("0.10")))
        portfolio.record_fill(_fill(ticker="B", price=Decimal("0.10")))
        result = rm.check(_signal(ticker="C"), portfolio)
        assert result is not None
        assert "max positions reached" in result.reason

    def test_allows_adding_to_existing_at_limit(self):
        rm = RiskManager(max_positions=2)
        portfolio = Portfolio()
        portfolio.record_fill(_fill(ticker="A", price=Decimal("0.10")))
        portfolio.record_fill(_fill(ticker="B", price=Decimal("0.10")))
        # Adding to existing position A should be OK
        result = rm.check(_signal(ticker="A"), portfolio)
        assert result is None

    def test_disabled_when_zero(self):
        rm = RiskManager(max_positions=0)
        portfolio = Portfolio()
        for i in range(50):
            portfolio.record_fill(_fill(ticker=f"T{i}", price=Decimal("0.01")))
        result = rm.check(_signal(ticker="T99"), portfolio)
        assert result is None


class TestMaxPortfolioPct:
    def test_allows_within_limit(self):
        rm = RiskManager(max_portfolio_pct=Decimal("50"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        # Invest $1000 out of $10000 = 10%
        portfolio.record_fill(_fill(price=Decimal("0.10"), qty=100))  # cost = $10
        result = rm.check(_signal(price=Decimal("0.50"), qty=10), portfolio)
        assert result is None

    def test_rejects_exceeding_limit(self):
        rm = RiskManager(max_portfolio_pct=Decimal("5"))
        portfolio = Portfolio(initial_balance=Decimal("1000"))
        # Already invested $40 (4%)
        portfolio.record_fill(_fill(price=Decimal("0.40"), qty=100))
        # New trade would be $50 (5%) -> total 9% > 5%
        result = rm.check(_signal(price=Decimal("0.50"), qty=100), portfolio)
        assert result is not None
        assert "portfolio allocation limit" in result.reason

    def test_disabled_when_zero(self):
        rm = RiskManager(max_portfolio_pct=Decimal("0"))
        portfolio = Portfolio(initial_balance=Decimal("100"))
        result = rm.check(_signal(price=Decimal("0.90"), qty=100), portfolio)
        assert result is None


class TestMaxLossPct:
    def test_allows_when_no_loss(self):
        rm = RiskManager(max_loss_pct=Decimal("10"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        result = rm.check(_signal(), portfolio)
        assert result is None

    def test_rejects_when_drawdown_exceeded(self):
        rm = RiskManager(max_loss_pct=Decimal("10"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        # Simulate a big loss: balance drops to $8000
        portfolio.balance = Decimal("8000")
        # No positions, so total value = $8000, loss = 20%
        result = rm.check(_signal(), portfolio)
        assert result is not None
        assert "max drawdown exceeded" in result.reason

    def test_disabled_when_zero(self):
        rm = RiskManager(max_loss_pct=Decimal("0"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        portfolio.balance = Decimal("1000")  # 90% loss
        result = rm.check(_signal(), portfolio)
        assert result is None


class TestCombinedChecks:
    def test_drawdown_checked_first(self):
        """Drawdown should be checked before position limits."""
        rm = RiskManager(
            max_position_size=100,
            max_loss_pct=Decimal("5"),
        )
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        portfolio.balance = Decimal("9000")  # 10% loss (exceeds 5% limit)
        result = rm.check(_signal(qty=5), portfolio)
        assert result is not None
        assert "max drawdown" in result.reason

    def test_all_pass(self):
        rm = RiskManager(
            max_position_size=100,
            max_positions=10,
            max_portfolio_pct=Decimal("80"),
            max_loss_pct=Decimal("20"),
        )
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        result = rm.check(_signal(qty=10), portfolio)
        assert result is None


class TestRiskRejection:
    def test_has_reason_and_signal(self):
        sig = _signal()
        rej = RiskRejection(reason="test", signal=sig)
        assert rej.reason == "test"
        assert rej.signal is sig

    def test_frozen(self):
        rej = RiskRejection(reason="test", signal=_signal())
        with pytest.raises(AttributeError):
            rej.reason = "changed"
