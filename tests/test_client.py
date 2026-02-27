"""Tests for Kalshi API client."""

from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest

from kalshi_bot.client import KalshiClient
from kalshi_bot.models import Market, Orderbook, PublicTrade


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def client(mock_session):
    return KalshiClient(session=mock_session)


class TestClientInit:
    def test_default_base_url(self, client):
        assert client.base_url == "https://api.elections.kalshi.com/trade-api/v2"

    def test_custom_base_url(self, mock_session):
        c = KalshiClient(session=mock_session, base_url="https://custom.api/v1")
        assert c.base_url == "https://custom.api/v1"

    def test_creates_session_if_none(self):
        c = KalshiClient()
        assert c.session is not None


class TestGetMarkets:
    def test_returns_markets(self, client, mock_session, sample_markets_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_markets_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        markets, cursor = client.get_markets()

        assert len(markets) == 1
        assert isinstance(markets[0], Market)
        assert markets[0].ticker == "KXBTC-26FEB21-50000"
        assert cursor == "next_page_cursor"

    def test_passes_params(self, client, mock_session, sample_markets_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_markets_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client.get_markets(limit=10, cursor="abc", series_ticker="KXBTC")

        args, kwargs = mock_session.get.call_args
        params = kwargs.get("params", {})
        assert params["limit"] == 10
        assert params["cursor"] == "abc"
        assert params["series_ticker"] == "KXBTC"

    def test_pagination(self, client, mock_session, sample_market_response):
        page1_resp = MagicMock()
        page1_resp.json.return_value = {
            "markets": [sample_market_response],
            "cursor": "page2",
        }
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.json.return_value = {
            "markets": [sample_market_response],
            "cursor": "",
        }
        page2_resp.raise_for_status = MagicMock()

        mock_session.get.side_effect = [page1_resp, page2_resp]

        markets = client.get_all_markets(series_ticker="KXBTC")
        assert len(markets) == 2


class TestGetMarket:
    def test_returns_single_market(self, client, mock_session, sample_market_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"market": sample_market_response}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        market = client.get_market("KXBTC-26FEB21-50000")

        assert isinstance(market, Market)
        assert market.ticker == "KXBTC-26FEB21-50000"
        mock_session.get.assert_called_once()
        url = mock_session.get.call_args[0][0]
        assert "KXBTC-26FEB21-50000" in url


class TestGetOrderbook:
    def test_returns_orderbook(self, client, mock_session, sample_orderbook_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_orderbook_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        ob = client.get_orderbook("KXBTC-26FEB21-50000")

        assert isinstance(ob, Orderbook)
        assert ob.ticker == "KXBTC-26FEB21-50000"
        assert len(ob.yes) == 3
        assert ob.yes[0].price == Decimal("0.65")


class TestGetTrades:
    def test_returns_trades(self, client, mock_session, sample_trades_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_trades_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        trades, cursor = client.get_trades(ticker="KXBTC-26FEB21-50000")

        assert len(trades) == 2
        assert isinstance(trades[0], PublicTrade)
        assert trades[0].yes_price == Decimal("0.65")
        assert cursor == ""

    def test_passes_ticker_param(self, client, mock_session, sample_trades_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_trades_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client.get_trades(ticker="T", limit=50)

        _, kwargs = mock_session.get.call_args
        params = kwargs.get("params", {})
        assert params["ticker"] == "T"
        assert params["limit"] == 50


class TestErrorHandling:
    def test_raises_on_http_error(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_session.get.return_value = mock_resp

        with pytest.raises(Exception, match="404"):
            client.get_market("NONEXISTENT")
