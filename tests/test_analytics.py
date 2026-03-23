"""Tests for Analytics module."""

from decimal import Decimal

import pytest

from kalshi_bot.analytics import Analytics, PortfolioSnapshot, TradeRecord
from kalshi_bot.models import Side


class TestTradeRecord:
    def test_pnl_per_contract(self):
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.40"), exit_price=Decimal("0.60"),
            quantity=10, pnl=Decimal("2.00"),
        )
        assert t.pnl_per_contract == Decimal("0.20")

    def test_is_win_positive(self):
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.40"), exit_price=Decimal("0.60"),
            quantity=10, pnl=Decimal("2.00"),
        )
        assert t.is_win is True

    def test_is_win_negative(self):
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.60"), exit_price=Decimal("0.40"),
            quantity=10, pnl=Decimal("-2.00"),
        )
        assert t.is_win is False

    def test_is_win_breakeven(self):
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.50"), exit_price=Decimal("0.50"),
            quantity=10, pnl=Decimal("0.00"),
        )
        assert t.is_win is False

    def test_frozen(self):
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.40"), exit_price=Decimal("0.60"),
            quantity=10, pnl=Decimal("2.00"),
        )
        with pytest.raises(AttributeError):
            t.ticker = "X"


class TestPortfolioSnapshot:
    def test_total_value(self):
        s = PortfolioSnapshot(cycle=1, balance=Decimal("8000"), invested=Decimal("2000"))
        assert s.total_value == Decimal("10000")


class TestAnalytics:
    def test_empty_state(self):
        a = Analytics()
        assert a.trade_count == 0
        assert a.win_count == 0
        assert a.loss_count == 0
        assert a.win_rate == Decimal("0")
        assert a.total_pnl == Decimal("0")
        assert a.avg_win == Decimal("0")
        assert a.avg_loss == Decimal("0")
        assert a.profit_factor is None
        assert a.max_drawdown_pct == Decimal("0")
        assert a.per_market_pnl() == {}

    def test_record_trade(self):
        a = Analytics()
        t = TradeRecord(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.40"), exit_price=Decimal("0.60"),
            quantity=10, pnl=Decimal("2.00"),
        )
        a.record_trade(t)
        assert a.trade_count == 1
        assert a.trades[0] is t

    def test_record_close(self):
        a = Analytics()
        a.record_close(
            ticker="T", side=Side.YES,
            entry_price=Decimal("0.40"), exit_price=Decimal("0.60"),
            quantity=10,
        )
        assert a.trade_count == 1
        assert a.trades[0].pnl == Decimal("2.00")
        assert a.trades[0].ticker == "T"

    def test_win_loss_tracking(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)  # win: +2.00
        a.record_close("B", Side.YES, Decimal("0.60"), Decimal("0.40"), 10)  # loss: -2.00
        a.record_close("C", Side.YES, Decimal("0.30"), Decimal("0.50"), 10)  # win: +2.00
        assert a.win_count == 2
        assert a.loss_count == 1
        assert a.win_rate == Decimal("200") / Decimal("3")  # 66.7%

    def test_total_pnl(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)  # +2.00
        a.record_close("B", Side.NO, Decimal("0.60"), Decimal("0.40"), 5)   # -1.00
        assert a.total_pnl == Decimal("1.00")

    def test_avg_win_loss(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.70"), 10)  # +3.00
        a.record_close("B", Side.YES, Decimal("0.40"), Decimal("0.50"), 10)  # +1.00
        a.record_close("C", Side.YES, Decimal("0.60"), Decimal("0.40"), 10)  # -2.00
        assert a.avg_win == Decimal("2.00")
        assert a.avg_loss == Decimal("-2.00")

    def test_profit_factor(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)  # +2.00
        a.record_close("B", Side.YES, Decimal("0.60"), Decimal("0.40"), 5)   # -1.00
        pf = a.profit_factor
        assert pf is not None
        assert pf == Decimal("2")  # 2.00 / 1.00

    def test_profit_factor_no_losses(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)
        assert a.profit_factor is None

    def test_per_market_pnl(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)  # +2.00
        a.record_close("A", Side.NO, Decimal("0.30"), Decimal("0.50"), 5)    # +1.00
        a.record_close("B", Side.YES, Decimal("0.60"), Decimal("0.40"), 10)  # -2.00
        pnl = a.per_market_pnl()
        assert pnl["A"] == Decimal("3.00")
        assert pnl["B"] == Decimal("-2.00")

    def test_drawdown_tracking(self):
        a = Analytics()
        a.record_snapshot(1, Decimal("10000"), Decimal("0"))       # total=10000, peak=10000
        a.record_snapshot(2, Decimal("9000"), Decimal("500"))      # total=9500, dd=5%
        a.record_snapshot(3, Decimal("8000"), Decimal("0"))        # total=8000, dd=20%
        a.record_snapshot(4, Decimal("9000"), Decimal("0"))        # total=9000, dd=10% (peak still 10000)
        assert a.max_drawdown_pct == Decimal("20")

    def test_drawdown_new_peak_resets(self):
        a = Analytics()
        a.record_snapshot(1, Decimal("10000"), Decimal("0"))
        a.record_snapshot(2, Decimal("8000"), Decimal("0"))        # dd=20%
        a.record_snapshot(3, Decimal("12000"), Decimal("0"))       # new peak
        a.record_snapshot(4, Decimal("11000"), Decimal("0"))       # dd from 12k = 8.3%
        # Max drawdown is still 20% from the first dip
        assert a.max_drawdown_pct == Decimal("20")

    def test_summary_dict(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)
        s = a.summary()
        assert s["total_trades"] == 1
        assert s["wins"] == 1
        assert s["losses"] == 0
        assert "win_rate" in s
        assert "per_market_pnl" in s

    def test_format_report_empty(self):
        a = Analytics()
        report = a.format_report()
        assert "No completed trades" in report

    def test_format_report_with_trades(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)
        a.record_close("B", Side.YES, Decimal("0.60"), Decimal("0.40"), 5)
        report = a.format_report()
        assert "TRADE PERFORMANCE REPORT" in report
        assert "Win Rate" in report
        assert "Per-Market P&L" in report

    def test_trades_returns_copy(self):
        a = Analytics()
        a.record_close("A", Side.YES, Decimal("0.40"), Decimal("0.60"), 10)
        trades = a.trades
        trades.clear()
        assert a.trade_count == 1  # original unchanged
