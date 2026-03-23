"""Thin requests wrapper for Kalshi public API."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from kalshi_bot.models import Market, Orderbook, PublicTrade

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

logger = logging.getLogger(__name__)

# Retry settings
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds
_BACKOFF_FACTOR = 2.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

# Pagination guard
MAX_PAGES = 500


class KalshiClient:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        base_url: str = BASE_URL,
        max_retries: int = _MAX_RETRIES,
    ):
        self.session = session or requests.Session()
        self.base_url = base_url
        self.max_retries = max_retries

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code in _RETRYABLE_STATUS_CODES:
                    wait = _INITIAL_BACKOFF * (_BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        "Retryable status %d on %s (attempt %d/%d), waiting %.1fs",
                        resp.status_code, path, attempt + 1, self.max_retries, wait,
                    )
                    if attempt < self.max_retries - 1:
                        time.sleep(wait)
                        continue
                resp.raise_for_status()
                return resp.json()
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                wait = _INITIAL_BACKOFF * (_BACKOFF_FACTOR ** attempt)
                logger.warning(
                    "%s on %s (attempt %d/%d), retrying in %.1fs",
                    type(exc).__name__, path, attempt + 1, self.max_retries, wait,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait)
        # If we exhausted retries on a retryable status code, raise the last response
        if last_exc is not None:
            raise last_exc
        # Shouldn't reach here, but just in case
        resp.raise_for_status()  # type: ignore[possibly-undefined]
        return resp.json()  # type: ignore[possibly-undefined]

    def get_markets(
        self,
        limit: int = 100,
        cursor: str = "",
        series_ticker: str = "",
        status: str = "",
    ) -> tuple[list[Market], str]:
        params: dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status

        data = self._get("/markets", params=params)
        markets = [Market.from_api(m) for m in data.get("markets", [])]
        return markets, data.get("cursor", "")

    def get_all_markets(self, **kwargs) -> list[Market]:
        all_markets: list[Market] = []
        cursor = ""
        seen_cursors: set[str] = set()
        page = 0
        while True:
            markets, cursor = self.get_markets(cursor=cursor, **kwargs)
            all_markets.extend(markets)
            page += 1
            if not cursor:
                break
            if cursor in seen_cursors:
                logger.warning(
                    "Duplicate cursor %r detected at page %d, stopping pagination",
                    cursor, page,
                )
                break
            if page >= MAX_PAGES:
                logger.warning(
                    "Hit max page limit (%d) in get_all_markets, stopping",
                    MAX_PAGES,
                )
                break
            seen_cursors.add(cursor)
        return all_markets

    def get_market(self, ticker: str) -> Market:
        data = self._get(f"/markets/{ticker}")
        return Market.from_api(data["market"])

    def get_orderbook(self, ticker: str) -> Orderbook:
        data = self._get(f"/markets/{ticker}/orderbook")
        return Orderbook.from_api(ticker, data)

    def get_trades(
        self,
        ticker: str = "",
        limit: int = 100,
        cursor: str = "",
    ) -> tuple[list[PublicTrade], str]:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor

        data = self._get("/markets/trades", params=params)
        trades = [PublicTrade.from_api(t) for t in data.get("trades", [])]
        return trades, data.get("cursor", "")
