# kalshi-bot Specification

## Overview

A paper trading bot that fetches real market data from Kalshi's public REST API
and simulates trades locally against real orderbook spreads. No real money or
authentication required.

## Public API Endpoints

Base URL: `https://api.elections.kalshi.com/trade-api/v2`

| Endpoint | Method | Description |
|---|---|---|
| `/markets` | GET | List markets (paginated via cursor) |
| `/markets/{ticker}` | GET | Single market details |
| `/markets/{ticker}/orderbook` | GET | Current orderbook (yes/no levels) |
| `/markets/trades` | GET | Recent public trades |

## Data Model

### Market
- `ticker`: unique identifier (e.g. `KXBTC-26FEB21-50000`)
- `title`: human-readable name
- `status`: open / closed / settled
- `result`: yes / no (when settled)
- `yes_bid` / `yes_ask`: best prices

### Orderbook
- `yes`: list of `[price, quantity]` levels
- `no`: list of `[price, quantity]` levels
- YES ask = 1.00 - best NO bid

### Paper Trading Rules
1. Orders are filled against real orderbook levels
2. Market orders walk all available levels
3. Limit orders stop at the specified price threshold
4. Fills reduce available quantity at each level
5. Balance is debited by fill price × quantity (in cents)
6. Positions track net contracts per market per side

### Portfolio
- Initial virtual balance: $100.00 (10000 cents)
- Track: open positions, realized P&L, unrealized P&L
- Settlement: when market resolves, winning contracts pay $1.00, losing pay $0

## Strategy: Mean Reversion

Buy YES when current price < moving average - threshold.
Buy NO when current price > moving average + threshold.
Close positions when price reverts toward the mean.

## CLI Interface

```
kalshi-bot run [--interval SECONDS] [--balance CENTS] [--series FILTER]
kalshi-bot status [--state-file PATH]
kalshi-bot markets [--series FILTER] [--limit N]
```
