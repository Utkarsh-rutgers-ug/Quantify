"""Offline regressions for secret-safe errors and server-priced paper trades."""
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["FINNHUB_API_KEY"] = "offline-test-token"

import traceback
import unittest
from unittest.mock import Mock, patch
import requests
from sqlalchemy.exc import SQLAlchemyError
from app import create_app
from models import db, Account, Position, Trade, QuoteSample
import services
from finnhub_api import _get, get_quote, FinnhubError
from quote_sampler import sample_watched_tickers


class SafeErrors(unittest.TestCase):
    def test_transport_and_response_errors_do_not_disclose_tokens(self):
        secret = "FAKE-SECRET-FOR-TEST"
        errors = [requests.ConnectionError(secret), requests.Timeout(secret),
                  requests.HTTPError(secret), requests.exceptions.JSONDecodeError(secret, secret, 0)]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch("finnhub_api.requests.get", side_effect=error):
                try:
                    _get("/quote", secret)
                    self.fail("Expected provider failure")
                except FinnhubError:
                    self.assertNotIn(secret, traceback.format_exc())
        response = Mock()
        response.json.return_value = {"error": secret}
        with patch("finnhub_api.requests.get", return_value=response):
            with self.assertRaises(FinnhubError) as caught:
                _get("/quote", secret)
            self.assertNotIn(secret, str(caught.exception))

    def test_invalid_quotes_are_rejected(self):
        for value in [-1, 0, "NaN", "Infinity", {}, "bad"]:
            with self.subTest(value=value), patch("finnhub_api._get", return_value={"c": value}):
                with self.assertRaises(FinnhubError):
                    get_quote("AAPL", "offline")


class TradeValidation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.user_id = services.create_user_with_account("Audit", "audit@test.invalid").id
        db.session.add(QuoteSample(ticker="AAPL", price=100))
        db.session.commit()
        self.client = self.app.test_client()
        self.payload = dict(user_id=self.user_id, ticker="AAPL", side="BUY", quantity=2)

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def assert_unmodified(self):
        self.assertEqual(Account.query.one().cash_balance, 100000)
        self.assertEqual(Trade.query.count(), 0)
        self.assertEqual(Position.query.count(), 0)

    def test_price_overrides_rejected_including_old_exploit(self):
        for price in [-100, 0, 1, 100, None, "NaN", "Infinity"]:
            response = self.client.post("/api/trades", json={**self.payload, "price": price})
            self.assertEqual(response.status_code, 400)
            self.assert_unmodified()

    def test_strict_inputs_and_malformed_json(self):
        cases = [("quantity", value) for value in [0, -1, 1.5, True, "2", None, 2**40]]
        cases += [("user_id", value) for value in [None, True, "1", 0, 1.1]]
        cases += [("ticker", value) for value in [None, {}, "", "<script>", "A"*11]]
        cases += [("side", value) for value in [None, [], "INVALID"]]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.assertEqual(self.client.post("/api/trades", json={**self.payload, key: value}).status_code, 400)
                self.assert_unmodified()
        for body in ["null", "[]", "{}", "{bad", '"text"']:
            self.assertEqual(self.client.post("/api/trades", data=body, content_type="application/json").status_code, 400)
            self.assert_unmodified()

    def test_invalid_server_prices_and_overflow_rejected(self):
        for value in [0, -1, float("nan"), float("inf"), "bad", 1e308]:
            with self.subTest(value=value), patch("services.latest_close", return_value=value):
                self.assertEqual(self.client.post("/api/trades", json=self.payload).status_code, 400)
                self.assert_unmodified()

    def test_service_rejects_fractional_and_boolean_quantity(self):
        for quantity in [1.5, True, "2"]:
            with self.assertRaises(ValueError):
                services.submit_trade(self.user_id, "AAPL", "BUY", quantity)
        self.assert_unmodified()

    def test_buy_sell_weighted_cost_and_rejections(self):
        first = self.client.post("/api/trades", json={**self.payload, "ticker": " aapl ", "side": "buy"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["price"], 100)
        with patch("services.latest_close", return_value=200):
            second = self.client.post("/api/trades", json=self.payload)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(Position.query.one().avg_cost, 150)
            sell = self.client.post("/api/trades", json={**self.payload, "side": "SELL", "quantity": 1})
        self.assertEqual(sell.status_code, 200)
        self.assertEqual(sell.json["realized_pnl"], 50)
        self.assertEqual(Account.query.one().cash_balance, 99600)
        self.assertEqual(Position.query.one().quantity, 3)
        for payload in [{**self.payload, "quantity": 1000000}, {**self.payload, "side": "SELL", "quantity": 4}]:
            self.assertEqual(self.client.post("/api/trades", json=payload).status_code, 400)
        self.assertEqual(Trade.query.count(), 3)

    def test_provider_failure_is_safe_in_api_and_sampler_logs(self):
        error = requests.ConnectionError("token=FAKE-SECRET-FOR-TEST")
        with patch("finnhub_api.requests.get", side_effect=error):
            result = self.client.post("/api/quote/AAPL")
            self.assertEqual(result.status_code, 502)
            self.assertNotIn("FAKE-SECRET", result.get_data(as_text=True))
            with patch("services.list_watched_tickers", return_value=["AAPL"]), self.assertLogs(self.app.logger, level="WARNING") as logs:
                sample_watched_tickers(self.app)
            self.assertNotIn("FAKE-SECRET", " ".join(logs.output))

    def test_failed_commit_rolls_back_and_next_trade_can_succeed(self):
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("private database details")), self.assertLogs(self.app.logger, level="ERROR") as logs:
            result = self.client.post("/api/trades", json=self.payload)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private database details", result.get_data(as_text=True))
        self.assertNotIn("private database details", " ".join(logs.output))
        self.assert_unmodified()
        self.assertEqual(self.client.post("/api/trades", json=self.payload).status_code, 200)


if __name__ == "__main__":
    unittest.main()
