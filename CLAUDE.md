# kalshi-bot

Paper trading bot for Kalshi prediction markets.

## Development

- Enter dev shell: `nix develop`
- Run tests: `pytest`
- Run with coverage: `pytest --cov=kalshi_bot`
- Run bot: `kalshi-bot run --interval 60`
- Check portfolio: `kalshi-bot status`
- List markets: `kalshi-bot markets`

## Architecture

- All prices use `Decimal` (never float)
- Domain models are frozen dataclasses
- Tests mock HTTP calls via `unittest.mock`
- Kalshi public API base: `https://api.elections.kalshi.com/trade-api/v2`

## Git

- Author: Teddy Tennant <teddytennant@icloud.com>
- Atomic commits per file/module
