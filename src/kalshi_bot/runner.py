"""CLI entry point (argparse, main polling loop)."""

from __future__ import annotations

import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path

from kalshi_bot.client import KalshiClient
from kalshi_bot.engine import PaperTradingEngine
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
    run_parser.add_argument("--balance", type=int, default=10000, help="Initial balance in cents")
    run_parser.add_argument("--series", type=str, default="", help="Filter by series ticker")
    run_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")

    status_parser = subparsers.add_parser("status", help="Show portfolio status")
    status_parser.add_argument("--state-file", type=str, default="state.json", help="State file path")

    markets_parser = subparsers.add_parser("markets", help="List available markets")
    markets_parser.add_argument("--series", type=str, default="", help="Filter by series ticker")
    markets_parser.add_argument("--limit", type=int, default=20, help="Max markets to show")

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
    print(f"Balance:      {portfolio.balance}")
    print(f"Initial:      {portfolio.initial_balance}")
    print(f"Realized P&L: {portfolio.realized_pnl}")
    positions = portfolio.positions
    if positions:
        print(f"\nPositions ({len(positions)}):")
        for (ticker, side), pos in positions.items():
            print(f"  {ticker} {side.value.upper():>3}: {pos.quantity} @ {pos.avg_price}")
    else:
        print("\nNo open positions.")


def run_cycle(
    client: KalshiClient,
    portfolio: Portfolio,
    strategy: Strategy,
) -> None:
    markets, _ = client.get_markets(limit=100)
    selected = strategy.select_markets(markets)

    engine = PaperTradingEngine(portfolio=portfolio, client=client)

    for market in selected:
        orderbook = client.get_orderbook(market.ticker)
        trades, _ = client.get_trades(ticker=market.ticker)
        signal = strategy.evaluate(market, orderbook, trades, portfolio)

        if signal is not None:
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
                    print(f"  Filled {signal.side.value.upper()} {signal.ticker}: "
                          f"{sum(f.quantity for f in fills)} contracts, cost {total}")
            except ValueError as e:
                print(f"  Order rejected: {e}")

    # Check for settlements on held positions
    held_tickers = list({ticker for ticker, _ in portfolio.positions})
    if held_tickers:
        engine.check_settlements(held_tickers)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    client = KalshiClient()

    if args.command == "markets":
        cmd_markets(client, series=args.series, limit=args.limit)
    elif args.command == "status":
        cmd_status(args.state_file)
    elif args.command == "run":
        state_path = Path(args.state_file)
        portfolio = load_state(state_path)
        if portfolio is None:
            portfolio = Portfolio(initial_balance=Decimal(args.balance))
            print(f"Starting new portfolio with balance: {portfolio.balance}")
        else:
            print(f"Loaded portfolio: balance={portfolio.balance}, "
                  f"positions={len(portfolio.positions)}")

        strategy = MeanReversionStrategy(
            window=10,
            threshold=Decimal("0.05"),
            order_quantity=10,
        )

        print(f"Running paper trading loop (interval={args.interval}s)...")
        try:
            while True:
                try:
                    run_cycle(client, portfolio, strategy)
                    save_state(portfolio, state_path)
                except Exception as e:
                    print(f"Cycle error: {e}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopping...")
            save_state(portfolio, state_path)
            print(f"State saved to {state_path}")


if __name__ == "__main__":
    main()
