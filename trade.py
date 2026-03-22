#!/usr/bin/env python3
"""12-hour trading session. Finds edge-based positions, monitors for settlements, sells at end."""

import time
from decimal import Decimal
from pathlib import Path

from kalshi_bot.client import KalshiClient
from kalshi_bot.engine import PaperTradingEngine
from kalshi_bot.models import Order, OrderStatus, OrderType, Side
from kalshi_bot.persistence import load_state, save_state
from kalshi_bot.portfolio import Portfolio

STATE_FILE = Path("sim_state.json")
DURATION_HOURS = 12


def buy(engine, portfolio, ticker, side, price, quantity, label=""):
    order = Order(
        ticker=ticker, side=side, order_type=OrderType.LIMIT,
        price=price, quantity=quantity, status=OrderStatus.PENDING,
    )
    try:
        fills = engine.submit_order(order)
        if fills:
            total = sum(f.total_cost for f in fills)
            qty = sum(f.quantity for f in fills)
            avg = total / qty if qty else price
            print(f"  BUY {label or ticker} {side.value.upper()}: {qty} @ {avg:.4f} = ${total:.2f}")
            return qty, total
    except ValueError as e:
        print(f"  REJECTED {label}: {e}")
    return 0, Decimal("0")


def sell_all(client, engine, portfolio):
    """Sell every open position."""
    total_proceeds = Decimal("0")
    for (ticker, side), pos in list(portfolio.positions.items()):
        name = ticker.split("-")[-1]
        try:
            fills = engine.sell_position(ticker, side, pos.quantity)
            if fills:
                total = sum(f.total_cost for f in fills)
                qty = sum(f.quantity for f in fills)
                avg = total / qty if qty else Decimal("0")
                pnl = total - pos.avg_price * qty
                total_proceeds += total
                print(f"  SOLD {name:>12} {side.value.upper()}: {qty:>5} @ {avg:.4f} = ${total:>8.2f}  (P&L: {pnl:+.2f})")
            else:
                print(f"  NO BIDS {name}: empty orderbook")
        except ValueError as e:
            print(f"  ERROR {name}: {e}")
    return total_proceeds


def check_settlements(client, engine, portfolio):
    """Check all held tickers for settlements. Returns count settled."""
    held = list({t for t, _ in portfolio.positions})
    settled = 0
    for ticker in held:
        try:
            market = client.get_market(ticker)
            if market.status == "settled":
                name = ticker.split("-")[-1]
                result = market.result
                # Get position info before settlement
                for side in (Side.YES, Side.NO):
                    pos = portfolio.get_position(ticker, side)
                    if pos:
                        won = side.value == result
                        settle_price = Decimal("1.00") if won else Decimal("0.00")
                        pnl = (settle_price - pos.avg_price) * pos.quantity
                        print(f"  SETTLED {name} {side.value.upper()}: {'WON' if won else 'LOST'} "
                              f"{pos.quantity} contracts, P&L: {pnl:+.2f}")
                portfolio.settle_market(ticker, result=result)
                settled += 1
        except Exception as e:
            print(f"  WARNING: settlement check failed for {ticker}: {e}")
    return settled


def find_edge_markets(client):
    """Find markets where ask < recent trade mean (positive edge)."""
    opportunities = []

    series_list = ["KXBOXING", "KXNBAGAME", "KXGDP", "KXNBA", "KXNHL", "KXCPI"]
    for series in series_list:
        try:
            markets, _ = client.get_markets(limit=100, series_ticker=series, status="open")
            for m in markets:
                if m.status not in ("open", "active"):
                    continue
                if m.yes_bid <= 0 or m.yes_ask <= 0:
                    continue
                spread = m.yes_ask - m.yes_bid
                if spread > Decimal("0.03") or spread <= 0:
                    continue

                try:
                    trades, _ = client.get_trades(ticker=m.ticker, limit=15)
                    if len(trades) < 5:
                        continue
                    prices = [t.yes_price for t in trades[:10]]
                    mean = sum(prices) / len(prices)
                    edge = mean - m.yes_ask
                    if edge > Decimal("0"):
                        opportunities.append({
                            "ticker": m.ticker,
                            "side": Side.YES,
                            "ask": m.yes_ask,
                            "bid": m.yes_bid,
                            "mean": mean,
                            "edge": edge,
                            "spread": spread,
                            "volume": m.volume,
                            "title": m.title[:60],
                        })
                    no_ask = Decimal("1.00") - m.yes_bid
                    if no_ask <= 0:
                        continue
                    no_mean = Decimal("1.00") - mean
                    no_edge = no_mean - no_ask
                    if no_edge > Decimal("0"):
                        opportunities.append({
                            "ticker": m.ticker,
                            "side": Side.NO,
                            "ask": no_ask,
                            "bid": Decimal("1.00") - m.yes_ask,
                            "mean": no_mean,
                            "edge": no_edge,
                            "spread": spread,
                            "volume": m.volume,
                            "title": m.title[:60],
                        })
                except Exception as e:
                    print(f"  WARNING: trade fetch failed for {m.ticker}: {e}")
            time.sleep(0.5)
        except Exception as e:
            if "429" in str(e):
                print(f"  Rate limited on {series}, waiting...")
                time.sleep(3)
            else:
                print(f"  WARNING: market fetch failed for {series}: {e}")

    opportunities.sort(key=lambda o: o["edge"], reverse=True)
    return opportunities


def print_status(portfolio, label=""):
    invested = sum(pos.avg_price * pos.quantity for pos in portfolio.positions.values())
    total = portfolio.balance + invested
    ret = (
        (total - portfolio.initial_balance) / portfolio.initial_balance * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    print(f"  {label}Balance: ${portfolio.balance:.2f} | Invested: ${invested:.2f} | "
          f"Total: ${total:.2f} | P&L: ${portfolio.realized_pnl:.2f} | Return: {ret:+.2f}%")


def run():
    client = KalshiClient()
    portfolio = load_state(STATE_FILE)
    if portfolio is None:
        portfolio = Portfolio(initial_balance=Decimal("10000"))
    engine = PaperTradingEngine(portfolio=portfolio, client=client)

    end_time = time.time() + DURATION_HOURS * 3600
    start_time = time.time()

    print("=" * 60)
    print(f"  12-HOUR TRADING SESSION")
    print(f"  Start: {time.strftime('%H:%M:%S')}")
    print(f"  End:   {time.strftime('%H:%M:%S', time.localtime(end_time))}")
    print("=" * 60)
    print_status(portfolio, "START: ")
    print()

    # =====================================================
    # PHASE 1: Initial position building via edge scanning
    # =====================================================
    print("=" * 60)
    print("PHASE 1: BUILDING POSITIONS")
    print("=" * 60)

    print("\n--- Scanning for edge-based opportunities ---")
    opportunities = find_edge_markets(client)
    print(f"  Found {len(opportunities)} markets with positive edge")
    trades_placed = 0
    for opp in opportunities:
        if trades_placed >= 12:
            break
        ticker = opp["ticker"]
        side = opp["side"]
        if portfolio.get_position(ticker, side):
            continue
        # Skip if spread eats most of the edge
        if opp["edge"] <= opp["spread"]:
            continue
        budget = min(Decimal("500"), portfolio.balance * Decimal("0.06"))
        if opp["ask"] <= 0:
            continue
        qty = min(500, int(budget / opp["ask"]))
        if qty >= 20:
            print(f"  {opp['title']}")
            print(f"    edge={opp['edge']:.4f} spread={opp['spread']} vol={opp['volume']}")
            bought, _ = buy(engine, portfolio, ticker, side, opp["ask"], qty,
                            ticker.split("-")[-1])
            if bought > 0:
                trades_placed += 1
            time.sleep(0.3)

    save_state(portfolio, STATE_FILE)

    print()
    print_status(portfolio, "AFTER BUYS: ")
    print(f"  Positions: {len(portfolio.positions)}")
    for (ticker, side), pos in portfolio.positions.items():
        name = ticker.split("-")[-1]
        inv = pos.avg_price * pos.quantity
        potential = (Decimal("1.00") - pos.avg_price) * pos.quantity
        print(f"    {name:>12} {side.value.upper()}: {pos.quantity:>5} @ {pos.avg_price:.4f} "
              f"= ${inv:.2f}  (win: +${potential:.2f})")

    # =====================================================
    # PHASE 2: Monitor for 12 hours
    # =====================================================
    print()
    print("=" * 60)
    print("PHASE 2: MONITORING (12 hours)")
    print("=" * 60)

    cycle = 0
    last_full_print = 0

    try:
        while time.time() < end_time:
            cycle += 1
            elapsed_min = (time.time() - start_time) / 60
            elapsed_hr = elapsed_min / 60

            # Check settlements every cycle
            settled = check_settlements(client, engine, portfolio)
            if settled > 0:
                save_state(portfolio, STATE_FILE)
                print_status(portfolio, f"  [{elapsed_hr:.1f}h] ")

            # Every 30 min: check for new opportunities and take profit
            if cycle % 6 == 0 and portfolio.balance > Decimal("200"):
                # Check for take-profit opportunities (bid > entry + 3c)
                for (ticker, side), pos in list(portfolio.positions.items()):
                    try:
                        ob = client.get_orderbook(ticker)
                        bid = ob.best_yes_bid if side == Side.YES else ob.best_no_bid
                        if bid and bid >= pos.avg_price + Decimal("0.03"):
                            fills = engine.sell_position(ticker, side, pos.quantity)
                            if fills:
                                total = sum(f.total_cost for f in fills)
                                qty = sum(f.quantity for f in fills)
                                pnl = total - pos.avg_price * qty
                                name = ticker.split("-")[-1]
                                print(f"  [{elapsed_hr:.1f}h] TAKE PROFIT {name}: "
                                      f"{qty} contracts, P&L: {pnl:+.2f}")
                                save_state(portfolio, STATE_FILE)
                    except Exception as e:
                        print(f"  WARNING: take-profit check failed for {ticker}: {e}")

            # Every hour: look for new edge-based opportunities
            if cycle % 12 == 0 and portfolio.balance > Decimal("500"):
                try:
                    new_opps = find_edge_markets(client)
                    for opp in new_opps[:3]:
                        ticker = opp["ticker"]
                        side = opp["side"]
                        if portfolio.get_position(ticker, side):
                            continue
                        if opp["edge"] <= opp["spread"]:
                            continue
                        budget = min(Decimal("400"), portfolio.balance * Decimal("0.05"))
                        if opp["ask"] <= 0:
                            continue
                        qty = min(300, int(budget / opp["ask"]))
                        if qty >= 20:
                            bought, _ = buy(engine, portfolio, ticker, side, opp["ask"], qty,
                                            ticker.split("-")[-1])
                            if bought:
                                save_state(portfolio, STATE_FILE)
                                break
                except Exception as e:
                    print(f"  WARNING: edge scan failed: {e}")

            # Print status every hour
            if elapsed_min - last_full_print >= 60:
                last_full_print = elapsed_min
                print()
                print_status(portfolio, f"  [{elapsed_hr:.1f}h] ")
                # Show position P&L
                for (ticker, side), pos in portfolio.positions.items():
                    try:
                        ob = client.get_orderbook(ticker)
                        bid = ob.best_yes_bid if side == Side.YES else ob.best_no_bid
                        if bid:
                            pnl_per = bid - pos.avg_price
                            name = ticker.split("-")[-1]
                            m = client.get_market(ticker)
                            status = m.status
                            print(f"    {name:>12}: bid={bid} pnl/c={pnl_per:+.4f} "
                                  f"qty={pos.quantity} status={status}")
                    except Exception as e:
                        print(f"  WARNING: status check failed for {ticker}: {e}")

            save_state(portfolio, STATE_FILE)

            # Sleep 5 min between cycles
            sleep_time = min(300, max(0, end_time - time.time()))
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving state...")
        save_state(portfolio, STATE_FILE)

    # =====================================================
    # PHASE 3: Final settlement check + sell all
    # =====================================================
    print()
    print("=" * 60)
    print("PHASE 3: FINAL LIQUIDATION")
    print("=" * 60)

    # Final settlement check
    print("\n--- Final settlement check ---")
    check_settlements(client, engine, portfolio)
    save_state(portfolio, STATE_FILE)

    # Sell all remaining
    if portfolio.positions:
        print("\n--- Selling all remaining positions ---")
        sell_all(client, engine, portfolio)
        save_state(portfolio, STATE_FILE)

    # Final report
    print()
    print("=" * 60)
    print("  SESSION COMPLETE")
    print("=" * 60)
    ret = (
        (portfolio.balance - portfolio.initial_balance) / portfolio.initial_balance * 100
        if portfolio.initial_balance
        else Decimal("0")
    )
    print(f"  Final Balance:   ${portfolio.balance:.2f}")
    print(f"  Initial Balance: ${portfolio.initial_balance:.2f}")
    print(f"  Realized P&L:    ${portfolio.realized_pnl:.2f}")
    print(f"  Return:          {ret:+.2f}%")
    print("=" * 60)
    save_state(portfolio, STATE_FILE)


if __name__ == "__main__":
    run()
