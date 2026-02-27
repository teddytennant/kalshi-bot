"""Tests for CLI entry point."""

import sys
import time
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from kalshi_bot.events import Event, EventBus, EventType
from kalshi_bot.models import (
    Fill,
    Market,
    Orderbook,
    OrderbookLevel,
    PublicTrade,
    Side,
)
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.runner import (
    build_parser,
    cmd_markets,
    cmd_run,
    cmd_status,
    format_event,
    print_portfolio_summary,
    run_cycle,
)


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
        assert args.cycles == 0
        assert args.verbose is False

    def test_run_cycles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--cycles", "3"])
        assert args.cycles == 3

    def test_run_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "-v"])
        assert args.verbose is True

    def test_dashboard_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["dashboard", "--interval", "30", "--balance", "5000"])
        assert args.command == "dashboard"
        assert args.interval == 30
        assert args.balance == 5000

    def test_dashboard_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["dashboard"])
        assert args.interval == 60
        assert args.balance == 10000
        assert args.state_file == "state.json"
        assert args.series == ""


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
        assert "Return:" in captured.out

    def test_no_state_file(self, tmp_path, capsys):
        cmd_status(str(tmp_path / "nonexistent.json"))
        captured = capsys.readouterr()
        assert "No state file" in captured.out


class TestFormatEvent:
    def test_cycle_start(self):
        e = Event(EventType.CYCLE_START, time.time(), {"cycle": 3})
        line = format_event(e)
        assert "Cycle 3 started" in line

    def test_cycle_end(self):
        e = Event(EventType.CYCLE_END, time.time(), {
            "cycle": 3, "markets": 15, "signals": 2, "fills": 1,
        })
        line = format_event(e)
        assert "Cycle 3 complete" in line
        assert "15 markets" in line
        assert "2 signals" in line
        assert "1 fills" in line

    def test_cycle_error(self):
        e = Event(EventType.CYCLE_ERROR, time.time(), {"error": "connection timeout"})
        line = format_event(e)
        assert "ERROR" in line
        assert "connection timeout" in line

    def test_markets_fetched(self):
        e = Event(EventType.MARKETS_FETCHED, time.time(), {"total": 100, "selected": 42})
        line = format_event(e)
        assert "100 markets" in line
        assert "42 selected" in line

    def test_signal_generated(self):
        e = Event(EventType.SIGNAL_GENERATED, time.time(), {
            "ticker": "KXBTC-26FEB", "side": "yes", "price": "0.65", "quantity": 10,
        })
        line = format_event(e)
        assert "SIGNAL YES" in line
        assert "KXBTC-26FEB" in line
        assert "0.65" in line

    def test_order_filled(self):
        e = Event(EventType.ORDER_FILLED, time.time(), {
            "ticker": "KXBTC-26FEB", "side": "yes", "quantity": 10, "total_cost": "6.50",
        })
        line = format_event(e)
        assert "FILLED YES" in line
        assert "10 contracts" in line
        assert "$6.50" in line

    def test_order_rejected(self):
        e = Event(EventType.ORDER_REJECTED, time.time(), {
            "ticker": "KXBTC-26FEB", "reason": "Insufficient balance",
        })
        line = format_event(e)
        assert "REJECTED" in line
        assert "Insufficient balance" in line

    def test_market_scanned_hidden_by_default(self):
        e = Event(EventType.MARKET_SCANNED, time.time(), {
            "ticker": "KXBTC-26FEB", "yes_bid": "0.65", "yes_ask": "0.67", "signal": None,
        })
        assert format_event(e, verbose=False) is None

    def test_market_scanned_shown_with_verbose(self):
        e = Event(EventType.MARKET_SCANNED, time.time(), {
            "ticker": "KXBTC-26FEB", "yes_bid": "0.65", "yes_ask": "0.67", "signal": None,
        })
        line = format_event(e, verbose=True)
        assert "KXBTC-26FEB" in line
        assert "0.65" in line
        assert "0.67" in line

    def test_market_scanned_with_signal(self):
        e = Event(EventType.MARKET_SCANNED, time.time(), {
            "ticker": "KXBTC-26FEB", "yes_bid": "0.65", "yes_ask": "0.67", "signal": "YES",
        })
        line = format_event(e, verbose=True)
        assert "YES" in line


class TestPrintPortfolioSummary:
    def test_positive_pnl(self, capsys):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.balance = Decimal("10250.00")
        p.realized_pnl = Decimal("250.00")
        print_portfolio_summary(p)
        out = capsys.readouterr().out
        assert "$10250.00" in out
        assert "+$250.00" in out
        assert "+2.50%" in out

    def test_negative_pnl(self, capsys):
        p = Portfolio(initial_balance=Decimal("10000.00"))
        p.balance = Decimal("9800.00")
        p.realized_pnl = Decimal("-200.00")
        print_portfolio_summary(p)
        out = capsys.readouterr().out
        assert "$9800.00" in out
        assert "$-200.00" in out


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


class TestRunCycleWithEventBus:
    @pytest.fixture
    def setup(self, mock_client):
        market = Market(
            ticker="T", title="T", status="open", result="",
            yes_bid=Decimal("0.65"), yes_ask=Decimal("0.67"),
            no_bid=Decimal("0.33"), no_ask=Decimal("0.35"),
            volume=1000, open_interest=100,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        strategy = MagicMock()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = ([market], "")
        mock_client.get_orderbook.return_value = Orderbook(
            ticker="T",
            yes=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
            no=tuple([OrderbookLevel(Decimal("0.33"), 120)]),
        )
        mock_client.get_trades.return_value = ([], "")
        return mock_client, strategy, market

    def test_emits_cycle_start_and_end(self, setup):
        client, strategy, _ = setup
        bus = EventBus()
        run_cycle(client, Portfolio(), strategy, event_bus=bus, cycle_number=1)

        events, _ = bus.drain_from(0)
        types = [e.event_type for e in events]
        assert EventType.CYCLE_START in types
        assert EventType.CYCLE_END in types
        assert events[0].data["cycle"] == 1

    def test_emits_markets_fetched(self, setup):
        client, strategy, _ = setup
        bus = EventBus()
        run_cycle(client, Portfolio(), strategy, event_bus=bus)

        events, _ = bus.drain_from(0)
        fetched = [e for e in events if e.event_type == EventType.MARKETS_FETCHED]
        assert len(fetched) == 1
        assert fetched[0].data["total"] == 1
        assert fetched[0].data["selected"] == 1

    def test_emits_market_scanned(self, setup):
        client, strategy, _ = setup
        bus = EventBus()
        run_cycle(client, Portfolio(), strategy, event_bus=bus)

        events, _ = bus.drain_from(0)
        scanned = [e for e in events if e.event_type == EventType.MARKET_SCANNED]
        assert len(scanned) == 1
        assert scanned[0].data["ticker"] == "T"
        assert scanned[0].data["yes_bid"] == "0.65"
        assert scanned[0].data["yes_ask"] == "0.67"
        assert scanned[0].data["signal"] is None

    def test_emits_signal_and_fill(self, setup):
        from kalshi_bot.strategy import TradeSignal
        from kalshi_bot.models import OrderType, Fill

        client, strategy, _ = setup
        strategy.evaluate.return_value = TradeSignal(
            ticker="T", side=Side.YES, order_type=OrderType.LIMIT,
            price=Decimal("0.65"), quantity=10,
        )

        bus = EventBus()
        with patch("kalshi_bot.runner.PaperTradingEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.submit_order.return_value = [
                Fill(ticker="T", side=Side.YES, price=Decimal("0.67"), quantity=10)
            ]
            run_cycle(client, Portfolio(), strategy, event_bus=bus)

        events, _ = bus.drain_from(0)
        types = [e.event_type for e in events]
        assert EventType.SIGNAL_GENERATED in types
        assert EventType.ORDER_FILLED in types

        signal_ev = [e for e in events if e.event_type == EventType.SIGNAL_GENERATED][0]
        assert signal_ev.data["ticker"] == "T"
        assert signal_ev.data["side"] == "yes"

        fill_ev = [e for e in events if e.event_type == EventType.ORDER_FILLED][0]
        assert fill_ev.data["quantity"] == 10

    def test_emits_order_rejected(self, setup):
        from kalshi_bot.strategy import TradeSignal
        from kalshi_bot.models import OrderType

        client, strategy, _ = setup
        strategy.evaluate.return_value = TradeSignal(
            ticker="T", side=Side.YES, order_type=OrderType.LIMIT,
            price=Decimal("0.65"), quantity=10,
        )

        bus = EventBus()
        with patch("kalshi_bot.runner.PaperTradingEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.submit_order.side_effect = ValueError("Insufficient balance")
            run_cycle(client, Portfolio(), strategy, event_bus=bus)

        events, _ = bus.drain_from(0)
        rejected = [e for e in events if e.event_type == EventType.ORDER_REJECTED]
        assert len(rejected) == 1
        assert "Insufficient balance" in rejected[0].data["reason"]

    def test_cycle_end_has_summary(self, setup):
        client, strategy, _ = setup
        bus = EventBus()
        run_cycle(client, Portfolio(), strategy, event_bus=bus, cycle_number=5)

        events, _ = bus.drain_from(0)
        end = [e for e in events if e.event_type == EventType.CYCLE_END][0]
        assert end.data["cycle"] == 5
        assert end.data["markets"] == 1
        assert end.data["signals"] == 0
        assert end.data["fills"] == 0

    def test_no_event_bus_still_prints(self, setup, capsys):
        """Without event_bus, run_cycle should still use print (backward compat)."""
        from kalshi_bot.strategy import TradeSignal
        from kalshi_bot.models import OrderType, Fill

        client, strategy, _ = setup
        strategy.evaluate.return_value = TradeSignal(
            ticker="T", side=Side.YES, order_type=OrderType.LIMIT,
            price=Decimal("0.65"), quantity=10,
        )

        with patch("kalshi_bot.runner.PaperTradingEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.submit_order.return_value = [
                Fill(ticker="T", side=Side.YES, price=Decimal("0.67"), quantity=10)
            ]
            run_cycle(client, Portfolio(), strategy)

        captured = capsys.readouterr()
        assert "Filled YES T" in captured.out


class TestCmdRun:
    @pytest.fixture
    def setup(self, mock_client, tmp_path):
        market = Market(
            ticker="T", title="T", status="open", result="",
            yes_bid=Decimal("0.65"), yes_ask=Decimal("0.67"),
            no_bid=Decimal("0.33"), no_ask=Decimal("0.35"),
            volume=1000, open_interest=100,
            event_ticker="E", series_ticker="S", subtitle="", close_time="",
        )
        strategy = MagicMock()
        strategy.select_markets.return_value = [market]
        strategy.evaluate.return_value = None
        mock_client.get_markets.return_value = ([market], "")
        mock_client.get_orderbook.return_value = Orderbook(
            ticker="T",
            yes=tuple([OrderbookLevel(Decimal("0.65"), 100)]),
            no=tuple([OrderbookLevel(Decimal("0.33"), 120)]),
        )
        mock_client.get_trades.return_value = ([], "")
        state_path = tmp_path / "state.json"
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        return mock_client, strategy, state_path, portfolio

    def test_runs_fixed_cycles(self, setup, capsys):
        client, strategy, state_path, portfolio = setup
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=2)
        out = capsys.readouterr().out
        assert "Cycle 1 started" in out
        assert "Cycle 2 started" in out
        assert "Cycle 1 complete" in out
        assert "Cycle 2 complete" in out
        assert "State saved" in out

    def test_saves_state_each_cycle(self, setup):
        from kalshi_bot.persistence import load_state

        client, strategy, state_path, portfolio = setup
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=1)
        assert state_path.exists()
        loaded = load_state(state_path)
        assert loaded is not None
        assert loaded.balance == portfolio.balance

    def test_prints_portfolio_summary(self, setup, capsys):
        client, strategy, state_path, portfolio = setup
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=1)
        out = capsys.readouterr().out
        assert "Balance: $10000.00" in out
        assert "Positions:" in out

    def test_verbose_shows_scans(self, setup, capsys):
        client, strategy, state_path, portfolio = setup
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=1, verbose=True)
        out = capsys.readouterr().out
        assert "scan T" in out

    def test_non_verbose_hides_scans(self, setup, capsys):
        client, strategy, state_path, portfolio = setup
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=1, verbose=False)
        out = capsys.readouterr().out
        assert "scan T" not in out

    def test_handles_cycle_error(self, setup, capsys):
        client, strategy, state_path, portfolio = setup
        client.get_markets.side_effect = Exception("API down")
        cmd_run(client, state_path, portfolio, strategy, interval=0, max_cycles=1)
        out = capsys.readouterr().out
        assert "ERROR" in out
        assert "API down" in out
