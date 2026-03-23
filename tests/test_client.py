"""Tests for Kalshi API client."""

from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from kalshi_bot.client import KalshiClient, MAX_PAGES
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


class TestRetryBackoff:
    """Tests for retry/backoff logic in _get."""

    @patch("kalshi_bot.client.time.sleep")
    def test_retries_on_500(self, mock_sleep, mock_session):
        client = KalshiClient(session=mock_session, max_retries=3)

        fail_resp = MagicMock()
        fail_resp.status_code = 500

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"market": {}}
        ok_resp.raise_for_status = MagicMock()

        mock_session.get.side_effect = [fail_resp, ok_resp]

        result = client._get("/test")
        assert result == {"market": {}}
        assert mock_session.get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("kalshi_bot.client.time.sleep")
    def test_retries_on_429(self, mock_sleep, mock_session):
        client = KalshiClient(session=mock_session, max_retries=3)

        fail_resp = MagicMock()
        fail_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"data": "ok"}
        ok_resp.raise_for_status = MagicMock()

        mock_session.get.side_effect = [fail_resp, ok_resp]
        result = client._get("/test")
        assert result == {"data": "ok"}

    @patch("kalshi_bot.client.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep, mock_session):
        client = KalshiClient(session=mock_session, max_retries=3)

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"ok": True}
        ok_resp.raise_for_status = MagicMock()

        mock_session.get.side_effect = [
            requests.exceptions.ConnectionError("reset"),
            ok_resp,
        ]

        result = client._get("/test")
        assert result == {"ok": True}
        assert mock_session.get.call_count == 2

    @patch("kalshi_bot.client.time.sleep")
    def test_retries_on_timeout(self, mock_sleep, mock_session):
        client = KalshiClient(session=mock_session, max_retries=2)

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"ok": True}
        ok_resp.raise_for_status = MagicMock()

        mock_session.get.side_effect = [
            requests.exceptions.Timeout("timed out"),
            ok_resp,
        ]

        result = client._get("/test")
        assert result == {"ok": True}

    @patch("kalshi_bot.client.time.sleep")
    def test_exhausted_retries_raises(self, mock_sleep, mock_session):
        client = KalshiClient(session=mock_session, max_retries=2)

        mock_session.get.side_effect = requests.exceptions.ConnectionError("down")

        with pytest.raises(requests.exceptions.ConnectionError):
            client._get("/test")
        assert mock_session.get.call_count == 2

    @patch("kalshi_bot.client.time.sleep")
    def test_exhausted_retries_on_status_raises(self, mock_sleep, mock_session):
        """After max retries on retryable status, raise_for_status is called."""
        client = KalshiClient(session=mock_session, max_retries=2)

        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("503")

        mock_session.get.return_value = fail_resp

        with pytest.raises(requests.exceptions.HTTPError):
            client._get("/test")
        assert mock_session.get.call_count == 2

    def test_no_retry_on_400(self, mock_session):
        """Non-retryable status codes should fail immediately."""
        client = KalshiClient(session=mock_session, max_retries=3)

        fail_resp = MagicMock()
        fail_resp.status_code = 400
        fail_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400")

        mock_session.get.return_value = fail_resp

        with pytest.raises(requests.exceptions.HTTPError):
            client._get("/test")
        assert mock_session.get.call_count == 1

    @patch("kalshi_bot.client.time.sleep")
    def test_backoff_increases(self, mock_sleep, mock_session):
        """Backoff should double on each retry."""
        client = KalshiClient(session=mock_session, max_retries=3)

        mock_session.get.side_effect = requests.exceptions.Timeout("slow")

        with pytest.raises(requests.exceptions.Timeout):
            client._get("/test")

        assert mock_sleep.call_count == 2  # retries 0 and 1, not the last
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)


class TestPaginationGuard:
    """Tests for max-page and duplicate cursor guards in get_all_markets."""

    def test_stops_on_duplicate_cursor(self, mock_session, sample_market_response):
        client = KalshiClient(session=mock_session)

        resp = MagicMock()
        resp.json.return_value = {
            "markets": [sample_market_response],
            "cursor": "stuck_cursor",
        }
        resp.raise_for_status = MagicMock()
        resp.status_code = 200
        mock_session.get.return_value = resp

        markets = client.get_all_markets()
        # First page returns cursor "stuck_cursor", second page returns same cursor -> stop
        assert mock_session.get.call_count == 2
        assert len(markets) == 2

    @patch("kalshi_bot.client.MAX_PAGES", 3)
    def test_stops_at_max_pages(self, mock_session, sample_market_response):
        client = KalshiClient(session=mock_session)

        call_count = 0

        def make_resp(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.json.return_value = {
                "markets": [sample_market_response],
                "cursor": f"cursor_{call_count}",
            }
            resp.raise_for_status = MagicMock()
            resp.status_code = 200
            return resp

        mock_session.get.side_effect = make_resp

        markets = client.get_all_markets()
        # Should stop at 3 pages
        assert mock_session.get.call_count == 3
        assert len(markets) == 3
