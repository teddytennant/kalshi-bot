"""CLI entry point (argparse, main polling loop)."""

from __future__ import annotations

import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

from kalshi_bot.client import KalshiClient
from kalshi_bot.engine import PaperTradingEngine
from kalshi_bot.events import Event, EventBus, EventType
from kalshi_bot.models import Order, OrderStatus, Side
from kalshi_bot.persistence import load_state, save_state
from kalshi_bot.portfolio import Portfolio
from kalshi_bot.strategy import MeanReversionStrategy, Strategy, TradeSignal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kalshi-bot",
        description="Paper trading bot for Kalshi prediction markets",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the paper trading loop")
    run_parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    run_parser.add_argument("--balance", type=int, default=10000, help="Initial balance in dollars")
    run_parser.add_argument("--series", type=str, default="", help="Filter by series ticker")
    run_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")
    run_parser.add_argument("--cycles", type=int, default=0, help="Run N cycles then exit (0=infinite)")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Show all events including market scans")
    run_parser.add_argument("--threshold", type=float, default=0.05, help="Mean reversion threshold (default: 0.05)")
    run_parser.add_argument("--quantity", type=int, default=10, help="Contracts per trade (default: 10)")
    run_parser.add_argument("--window", type=int, default=10, help="Trade history window (default: 10)")
    run_parser.add_argument("--min-volume", type=int, default=0, help="Min market volume filter")
    run_parser.add_argument("--take-profit", type=float, default=0, help="Sell when per-contract gain >= threshold (0=disabled)")
    run_parser.add_argument("--stop-loss", type=float, default=0, help="Sell when per-contract loss >= threshold (0=disabled)")

    status_parser = subparsers.add_parser("status", help="Show portfolio status")
    status_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")

    markets_parser = subparsers.add_parser("markets", help="List available markets")
    markets_parser.add_argument("--series", type=str, default="", help="Filter by series ticker")
    markets_parser.add_argument("--limit", type=int, default=20, help="Max markets to show")

    dash_parser = subparsers.add_parser("dashboard", help="Launch TUI dashboard")
    dash_parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    dash_parser.add_argument("--balance", type=int, default=10000, help="Initial balance in dollars")
    dash_parser.add_argument("--series", type=str, default="", help="Filter by series ticker")
    dash_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")
    dash_parser.add_argument("--threshold", type=float, default=0.05, help="Mean reversion threshold (default: 0.05)")
    dash_parser.add_argument("--quantity", type=int, default=10, help="Contracts per trade (default: 10)")
    dash_parser.add_argument("--window", type=int, default=10, help="Trade history window (default: 10)")
    dash_parser.add_argument("--min-volume", type=int, default=0, help="Min market volume filter")
    dash_parser.add_argument("--take-profit", type=float, default=0, help="Sell when per-contract gain >= threshold (0=disabled)")
    dash_parser.add_argument("--stop-loss", type=float, default=0, help="Sell when per-contract loss >= threshold (0=disabled)")

    return parser


def cmd_markets(client: KalshiClient, series: str, limit: int) -> None:
    kwargs = {"limit": limit}
    if series:
        kwargs["series_ticker"] = series
    markets, _ = client.get_markets(**kwargs)
    if not markets:
        print("No markets found.")
        return
    print(f"{'Ticker':<30} {'Yes Bid':>8} {'Yes Ask':>8} {'Volume':>8}  Title")
    print("-" * 90)
    for m in markets:
        print(f"{m.ticker:<30} {m.yes_bid:>8} {m.yes_ask:>8} {m.volume:>8}  {m.title[:40]}")


def cmd_status(state_file: str) -> None:
    portfolio = load_state(Path(state_file))
    if portfolio is None:
        print(f"No state file found at {state_file}")
        return
    print(f"Balance:      ${portfolio.balance:.2f}")
    print(f"Initial:      ${portfolio.initial_balance:.2f}")
    print(f"Realized P&L: ${portfolio.realized_pnl:.2f}")
    ret = (
        (portfolio.balance - portfolio.initial_balance)
        / portfolio.initial_balance
        * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    print(f"Return:       {'+' if ret >= 0 else ''}{ret:.2f}%")
    positions = portfolio.positions
    if positions:
        print(f"\nPositions ({len(positions)}):")
        print(f"  {'Ticker':<25} {'Side':>4} {'Qty':>5} {'Avg Price':>10}")
        print(f"  {'-'*25} {'-'*4} {'-'*5} {'-'*10}")
        for (ticker, side), pos in positions.items():
            print(f"  {ticker:<25} {side.value.upper():>4} {pos.quantity:>5} {pos.avg_price:>10.4f}")
    else:
        print("\nNo open positions.")


def format_event(event: Event, verbose: bool = False) -> Optional[str]:
    """Format an Event as a plain-text log line. Returns None to skip."""
    ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
    d = event.data
    et = event.event_type

    if et == EventType.CYCLE_START:
        return f"[{ts}] --- Cycle {d.get('cycle', '?')} started ---"

    if et == EventType.CYCLE_END:
        exits = d.get("exits", 0)
        exits_str = f", {exits} exits" if exits else ""
        return (
            f"[{ts}] Cycle {d.get('cycle', '?')} complete: "
            f"{d.get('markets', 0)} markets scanned, "
            f"{d.get('signals', 0)} signals, "
            f"{d.get('fills', 0)} fills"
            f"{exits_str}"
        )

    if et == EventType.CYCLE_ERROR:
        return f"[{ts}] ERROR: {d.get('error', '?')}"

    if et == EventType.MARKETS_FETCHED:
        return (
            f"[{ts}] Fetched {d.get('total', 0)} markets, "
            f"{d.get('selected', 0)} selected by strategy"
        )

    if et == EventType.SIGNAL_GENERATED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] SIGNAL {side} {d.get('ticker', '?')} "
            f"@ {d.get('price', '?')} x {d.get('quantity', '?')}"
        )

    if et == EventType.ORDER_FILLED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] FILLED {side} {d.get('ticker', '?')}: "
            f"{d.get('quantity', '?')} contracts, cost ${d.get('total_cost', '?')}"
        )

    if et == EventType.ORDER_REJECTED:
        return (
            f"[{ts}] REJECTED {d.get('ticker', '?')}: "
            f"{d.get('reason', '?')}"
        )

    if et == EventType.EXIT_SIGNAL:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] EXIT {side} {d.get('ticker', '?')} "
            f"reason={d.get('reason', '?')} "
            f"pnl_per_contract={d.get('pnl_per_contract', '?')}"
        )

    if et == EventType.POSITION_CLOSED:
        side = d.get("side", "?").upper()
        return (
            f"[{ts}] CLOSED {side} {d.get('ticker', '?')}: "
            f"{d.get('quantity', '?')} contracts @ {d.get('price', '?')}"
        )

    if et == EventType.MARKET_SCANNED and verbose:
        signal = d.get("signal")
        signal_str = f" -> {signal}" if signal else ""
        return (
            f"[{ts}]   scan {d.get('ticker', '?'):<30} "
            f"bid={d.get('yes_bid', '--'):>6} ask={d.get('yes_ask', '--'):>6}"
            f"{signal_str}"
        )

    return None


def print_portfolio_summary(portfolio: Portfolio) -> None:
    """Print a one-line portfolio summary."""
    ret = (
        (portfolio.balance - portfolio.initial_balance)
        / portfolio.initial_balance
        * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    pnl_sign = "+" if portfolio.realized_pnl >= 0 else ""
    ret_sign = "+" if ret >= 0 else ""
    n_pos = len(portfolio.positions)
    print(
        f"         Balance: ${portfolio.balance:.2f} | "
        f"P&L: {pnl_sign}${portfolio.realized_pnl:.2f} | "
        f"Return: {ret_sign}{ret:.2f}% | "
        f"Positions: {n_pos}"
    )


def run_cycle(
    client: KalshiClient,
    portfolio: Portfolio,
    strategy: Strategy,
    event_bus: Optional[EventBus] = None,
    cycle_number: int = 0,
    series: str = "",
    take_profit: Decimal = Decimal("0"),
    stop_loss: Decimal = Decimal("0"),
) -> None:
    if event_bus:
        event_bus.emit(EventType.CYCLE_START, cycle=cycle_number)

    kwargs: dict = {"limit": 100}
    if series:
        kwargs["series_ticker"] = series
    markets, _ = client.get_markets(**kwargs)
    selected = strategy.select_markets(markets)

    if event_bus:
        event_bus.emit(
            EventType.MARKETS_FETCHED,
            cycle=cycle_number,
            total=len(markets),
            selected=len(selected),
        )

    engine = PaperTradingEngine(portfolio=portfolio, client=client)

    signals_count = 0
    fills_count = 0

    for market in selected:
        orderbook = client.get_orderbook(market.ticker)
        trades, _ = client.get_trades(ticker=market.ticker)
        signal = strategy.evaluate(market, orderbook, trades, portfolio)

        if event_bus:
            event_bus.emit(
                EventType.MARKET_SCANNED,
                ticker=market.ticker,
                yes_bid=str(market.yes_bid),
                yes_ask=str(market.yes_ask),
                signal=signal.side.value.upper() if signal else None,
            )

        if signal is not None:
            signals_count += 1
            if event_bus:
                event_bus.emit(
                    EventType.SIGNAL_GENERATED,
                    ticker=signal.ticker,
                    side=signal.side.value,
                    price=str(signal.price),
                    quantity=signal.quantity,
                )

            order = Order(
                ticker=signal.ticker,
                side=signal.side,
                order_type=signal.order_type,
                price=signal.price,
                quantity=signal.quantity,
                status=OrderStatus.PENDING,
            )
            try:
                fills = engine.submit_order(order)
                if fills:
                    total = sum(f.total_cost for f in fills)
                    qty = sum(f.quantity for f in fills)
                    fills_count += len(fills)
                    if event_bus:
                        event_bus.emit(
                            EventType.ORDER_FILLED,
                            ticker=signal.ticker,
                            side=signal.side.value,
                            quantity=qty,
                            total_cost=str(total),
                        )
                    else:
                        print(f"  Filled {signal.side.value.upper()} {signal.ticker}: "
                              f"{qty} contracts, cost {total}")
            except ValueError as e:
                if event_bus:
                    event_bus.emit(
                        EventType.ORDER_REJECTED,
                        ticker=signal.ticker,
                        reason=str(e),
                    )
                else:
                    print(f"  Order rejected: {e}")

    # Exit monitoring: check positions for take-profit / stop-loss
    exits_count = 0
    if take_profit > 0 or stop_loss > 0:
        positions_snapshot = list(portfolio.positions.items())
        for (ticker, side), pos in positions_snapshot:
            orderbook = client.get_orderbook(ticker)
            if side == Side.YES:
                current_bid = orderbook.best_yes_bid
            else:
                current_bid = orderbook.best_no_bid

            if current_bid is None:
                continue

            per_contract_pnl = current_bid - pos.avg_price

            reason = None
            if take_profit > 0 and per_contract_pnl >= take_profit:
                reason = "take_profit"
            elif stop_loss > 0 and per_contract_pnl <= -stop_loss:
                reason = "stop_loss"

            if reason is None:
                continue

            if event_bus:
                event_bus.emit(
                    EventType.EXIT_SIGNAL,
                    ticker=ticker,
                    side=side.value,
                    reason=reason,
                    pnl_per_contract=str(per_contract_pnl),
                )

            try:
                sell_fills = engine.sell_position(ticker, side, pos.quantity)
                if sell_fills:
                    exits_count += 1
                    total = sum(f.total_cost for f in sell_fills)
                    qty = sum(f.quantity for f in sell_fills)
                    if event_bus:
                        event_bus.emit(
                            EventType.POSITION_CLOSED,
                            ticker=ticker,
                            side=side.value,
                            quantity=qty,
                            price=str(total / qty) if qty else "0",
                            reason=reason,
                        )
                    else:
                        print(f"  Closed {side.value.upper()} {ticker}: "
                              f"{qty} contracts ({reason})")
            except ValueError as e:
                if event_bus:
                    event_bus.emit(
                        EventType.ORDER_REJECTED,
                        ticker=ticker,
                        reason=str(e),
                    )
                else:
                    print(f"  Exit sell failed for {ticker}: {e}")

    # Check for settlements on held positions
    held_tickers = list({ticker for ticker, _ in portfolio.positions})
    if held_tickers:
        engine.check_settlements(held_tickers)

    if event_bus:
        event_bus.emit(
            EventType.CYCLE_END,
            cycle=cycle_number,
            markets=len(selected),
            signals=signals_count,
            fills=fills_count,
            exits=exits_count,
        )


def cmd_run(
    client: KalshiClient,
    state_path: Path,
    portfolio: Portfolio,
    strategy: Strategy,
    interval: int,
    max_cycles: int = 0,
    verbose: bool = False,
    series: str = "",
    take_profit: Decimal = Decimal("0"),
    stop_loss: Decimal = Decimal("0"),
) -> None:
    """Run the trading loop with structured event output."""
    event_bus = EventBus()
    cursor = 0
    cycle = 0

    print(f"Running paper trading loop (interval={interval}s, "
          f"cycles={'infinite' if max_cycles == 0 else max_cycles}"
          f"{', series=' + series if series else ''})...")
    print_portfolio_summary(portfolio)
    print()

    try:
        while max_cycles == 0 or cycle < max_cycles:
            cycle += 1
            try:
                run_cycle(
                    client, portfolio, strategy,
                    event_bus=event_bus, cycle_number=cycle,
                    series=series,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )
                save_state(portfolio, state_path)
            except Exception as e:
                event_bus.emit(EventType.CYCLE_ERROR, cycle=cycle, error=str(e))

            # Drain and print all events from this cycle
            events, cursor = event_bus.drain_from(cursor)
            for event in events:
                line = format_event(event, verbose=verbose)
                if line is not None:
                    print(line)

            # Print portfolio summary after each cycle
            print_portfolio_summary(portfolio)
            print()

            if max_cycles == 0 or cycle < max_cycles:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopping...")

    save_state(portfolio, state_path)
    print(f"State saved to {state_path}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "markets":
        client = KalshiClient()
        cmd_markets(client, series=args.series, limit=args.limit)
    elif args.command == "status":
        cmd_status(args.state_file)
    elif args.command == "run":
        client = KalshiClient()
        state_path = Path(args.state_file)
        portfolio = load_state(state_path)
        if portfolio is None:
            portfolio = Portfolio(initial_balance=Decimal(args.balance))
            print(f"Starting new portfolio with balance: ${portfolio.balance:.2f}")
        else:
            print(f"Loaded portfolio: balance=${portfolio.balance:.2f}, "
                  f"positions={len(portfolio.positions)}")

        strategy = MeanReversionStrategy(
            window=args.window,
            threshold=Decimal(str(args.threshold)),
            order_quantity=args.quantity,
            min_volume=args.min_volume,
        )

        cmd_run(
            client=client,
            state_path=state_path,
            portfolio=portfolio,
            strategy=strategy,
            interval=args.interval,
            max_cycles=args.cycles,
            verbose=args.verbose,
            series=args.series,
            take_profit=Decimal(str(args.take_profit)),
            stop_loss=Decimal(str(args.stop_loss)),
        )
    elif args.command == "dashboard":
        from kalshi_bot.tui import DashboardApp

        app = DashboardApp(
            interval=args.interval,
            balance=args.balance,
            series=args.series,
            state_file=args.state_file,
            threshold=Decimal(str(args.threshold)),
            order_quantity=args.quantity,
            window=args.window,
            min_volume=args.min_volume,
            take_profit=Decimal(str(args.take_profit)),
            stop_loss=Decimal(str(args.stop_loss)),
        )
        app.run()


if __name__ == "__main__":
    main()
