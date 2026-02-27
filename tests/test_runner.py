"""Tests for CLI entry point."""

import sys
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from kalshi_bot.models import (
    Fill,
    Market,
    Orderbook,
    OrderbookLevel,
    PublicTrade,
    Side,
)
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.runner import build_parser, cmd_markets, cmd_status, run_cycle


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def sample_markets():
    return [
        Market(
            ticker="A",
            title="Market A",
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
        ),
        Market(
            ticker="B",
            title="Market B",
            status="open",
            result="",
            yes_bid=Decimal("0.50"),
            yes_ask=Decimal("0.52"),
            no_bid=Decimal("0.48"),
            no_ask=Decimal("0.50"),
            volume=500,
            open_interest=50,
            event_ticker="E",
            series_ticker="S",
            subtitle="",
            close_time="",
        ),
    ]


class TestBuildParser:
    def test_run_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--interval", "30", "--balance", "5000"])
        assert args.command == "run"
        assert args.interval == 30
        assert args.balance == 5000

    def test_status_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["status", "--state-file", "/tmp/state.json"])
        assert args.command == "status"
        assert args.state_file == "/tmp/state.json"

    def test_markets_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["markets", "--series", "KXBTC", "--limit", "5"])
        assert args.command == "markets"
        assert args.series == "KXBTC"
        assert args.limit == 5

    def test_run_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.interval == 60
        assert args.balance == 10000
        assert args.state_file == "state.json"


class TestCmdMarkets:
    def test_lists_markets(self, mock_client, sample_markets, capsys):
        mock_client.get_markets.return_value = (sample_markets, "")
        cmd_markets(mock_client, series="", limit=10)
        captured = capsys.readouterr()
        assert "A" in captured.out
        assert "Market A" in captured.out
        assert "B" in captured.out

    def test_series_filter(self, mock_client, sample_markets, capsys):
        mock_client.get_markets.return_value = (sample_markets, "")
        cmd_markets(mock_client, series="S", limit=10)
        _, kwargs = mock_client.get_markets.call_args
        assert kwargs.get("series_ticker") == "S"


class TestCmdStatus:
    def test_shows_balance(self, tmp_path, capsys):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.record_fill(Fill(ticker="T", side=Side.YES, price=Decimal("0.65"), quantity=10))
        state_file = tmp_path / "state.json"
        from kalshi_bot.persistence import save_state

        save_state(p, state_file)
        cmd_status(str(state_file))
        captured = capsys.readouterr()
        assert "9993.50" in captured.out
        assert "T" in captured.out

    def test_no_state_file(self, tmp_path, capsys):
        cmd_status(str(tmp_path / "nonexistent.json"))
        captured = capsys.readouterr()
        assert "No state file" in captured.out


class TestRunCycle:
    def test_evaluates_strategy_for_each_market(self, mock_client):
        portfolio = Portfolio()
        strategy = MagicMock()
        strategy.select_markets.return_value = [
            Market(
                ticker="T", title="T", status="open", result="",
                yes_bid=Decimal("0.65"), yes_ask=Decimal("0.67"),
                no_bid=Decimal("0.33"), no_ask=Decimal("0.35"),
                volume=1000, open_interest=100,
                event_ticker="E", series_ticker="S", subtitle="", close_time="",
            )
        ]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = (strategy.select_markets.return_value, "")
        mock_client.get_orderbook.return_value = Orderbook(
            ticker="T",
            yes=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
            no=tuple([OrderbookLevel(Decimal("0.33"), 120)]),
        )
        mock_client.get_trades.return_value = ([], "")

        run_cycle(mock_client, portfolio, strategy)

        strategy.evaluate.assert_called_once()

    def test_submits_order_on_signal(self, mock_client):
        from kalshi_bot.strategy import TradeSignal
        from kalshi_bot.models import OrderType

        portfolio = Portfolio()
        strategy = MagicMock()
        market = Market(
            ticker="T", title="T", status="open", result="",
            yes_bid=Decimal("0.65"), yes_ask=Decimal("0.67"),
            no_bid=Decimal("0.33"), no_ask=Decimal("0.35"),
            volume=1000, open_interest=100,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = TradeSignal(
            ticker="T",
            side=Side.YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.65"),
            quantity=10,
        )
        mock_client.get_markets.return_value = ([market], "")
        mock_client.get_orderbook.return_value = Orderbook(
            ticker="T",
            yes=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
            no=tuple([OrderbookLevel(Decimal("0.33"), 120)]),
        )
        mock_client.get_trades.return_value = ([], "")

        with patch("kalshi_bot.runner.PaperTradingEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.submit_order.return_value = []
            run_cycle(mock_client, portfolio, strategy)
            mock_engine.submit_order.assert_called_once()
