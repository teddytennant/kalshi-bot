"""Thin requests wrapper for Kalshi public API."""

from __future__ import annotations

from typing import Optional

import requests

from kalshi_bot.models import Market, Orderbook, PublicTrade

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiClient:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        base_url: str = BASE_URL,
    ):
        self.session = session or requests.Session()
        self.base_url = base_url

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

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
        while True:
            markets, cursor = self.get_markets(cursor=cursor, **kwargs)
            all_markets.extend(markets)
            if not cursor:
                break
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
