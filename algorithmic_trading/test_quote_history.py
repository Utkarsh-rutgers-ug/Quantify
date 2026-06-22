"""Offline checks for Finnhub quote storage, chart bucketing, and trade pricing."""
import os
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["FINNHUB_API_KEY"] = "offline-test-token"

from app import create_app
from models import db, QuoteSample
from finnhub_api import FinnhubQuote
import services


def fake_quote(ticker, token):
    return FinnhubQuote(
        ticker=ticker,
        price=190.0,
        open=188.0,
        high=192.0,
        low=187.5,
        previous_close=189.0,
        change=1.0,
        change_percent=0.53,
        provider_timestamp=0,
        fetched_at=datetime.utcnow(),
    )


def main():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = services.create_user_with_account("Quote Tester", "quote@test.local")
        with patch("services.get_quote", fake_quote):
            stored = services.fetch_and_store_quote("AAPL")
        assert stored["price"] == 190.0
        assert services.latest_close("AAPL") == 190.0

        start = datetime.utcnow() - timedelta(days=3)
        for index in range(16):
            price = 180 + index
            db.session.add(
                QuoteSample(
                    ticker="AAPL",
                    timestamp=start + timedelta(hours=index * 5),
                    price=price,
                    high=price + 2,
                    low=price - 2,
                )
            )
        db.session.commit()

        week = services.get_quote_chart("AAPL", "1w")
        month = services.get_quote_chart("AAPL", "1m")
        assert week["multi_line"] is False and len(week["points"]) > 1
        assert month["multi_line"] is True and len(month["points"]) > 1
        assert all({"close", "high", "low"} <= point.keys() for point in month["points"])

        trade = services.submit_trade(user.id, "AAPL", "BUY", 10)
        assert trade["price"] == services.latest_close("AAPL")
        assert services.get_positions(user.id)[0]["last_price"] == trade["price"]

        client = app.test_client()
        chart_response = client.get("/api/chart/AAPL?range=1m")
        assert chart_response.status_code == 200
        assert chart_response.get_json()["multi_line"] is True

        with patch("services.get_quote", fake_quote):
            quote_response = client.post("/api/quote/MSFT")
        assert quote_response.status_code == 200
        assert quote_response.get_json()["price"] == 190.0

        services.submit_trade(user.id, "MSFT", "BUY", 5)
        performance_response = client.get(f"/api/performance?user_id={user.id}")
        assert performance_response.status_code == 200
        performance = performance_response.get_json()
        assert len(performance["curve"]) >= 3
        assert performance["summary"]["equity_start"] == services.STARTING_BALANCE
        assert performance["summary"]["equity_end"] == services.get_portfolio_summary(
            user.id
        )["total_equity"]
        print("Quote history, chart bucketing, and sampled-price trading checks passed.")


if __name__ == "__main__":
    main()
