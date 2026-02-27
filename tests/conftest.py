"""Shared fixtures with realistic Kalshi API response data."""

import pytest
from decimal import Decimal


@pytest.fixture
def sample_market_response():
    """Raw API response for a single market."""
    return {
        "ticker": "KXBTC-26FEB21-50000",
        "title": "Will Bitcoin hit $50,000 by Feb 26?",
        "status": "open",
        "result": "",
        "yes_bid": 65,
        "yes_ask": 67,
        "no_bid": 33,
        "no_ask": 35,
        "volume": 12345,
        "open_interest": 500,
        "event_ticker": "KXBTC",
        "series_ticker": "KXBTC",
        "subtitle": "Bitcoin price target",
        "close_time": "2021-02-26T23:59:59Z",
    }


@pytest.fixture
def sample_markets_response(sample_market_response):
    """Raw API response for market listing."""
    return {
        "markets": [sample_market_response],
        "cursor": "next_page_cursor",
    }


@pytest.fixture
def sample_orderbook_response():
    """Raw API response for an orderbook."""
    return {
        "orderbook": {
            "yes": [[65, 100], [63, 200], [60, 150]],
            "no": [[33, 120], [30, 80], [28, 200]],
        }
    }


@pytest.fixture
def sample_trades_response():
    """Raw API response for public trades."""
    return {
        "trades": [
            {
                "ticker": "KXBTC-26FEB21-50000",
                "yes_price": 65,
                "no_price": 35,
                "count": 10,
                "taker_side": "yes",
                "created_time": "2021-02-25T10:00:00Z",
            },
            {
                "ticker": "KXBTC-26FEB21-50000",
                "yes_price": 66,
                "no_price": 34,
                "count": 5,
                "taker_side": "no",
                "created_time": "2021-02-25T10:01:00Z",
            },
        ],
        "cursor": "",
    }


@pytest.fixture
def sample_candlesticks_response():
    """Raw API response for candlestick data."""
    return {
        "candlesticks": [
            {
                "ticker": "KXBTC-26FEB21-50000",
                "open": 60,
                "high": 68,
                "low": 58,
                "close": 65,
                "volume": 500,
                "start_period_ts": 1614240000,
                "end_period_ts": 1614243600,
            },
        ]
    }
