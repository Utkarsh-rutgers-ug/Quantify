"""Offline checks for leakage, gaps, benchmark adjustment, and atomic imports."""
import io
import os
import unittest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
from app import create_app
from models import db, NewsArticle
from event_study import EventPrice, NewsEvent, import_prices, measure, study, utc


class EventStudyTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.start = datetime(2026, 9, 1, 14)
        self.market = [(self.start + timedelta(minutes=i), 100) for i in range(-1, 61)]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_first_crossing_and_market_adjustment(self):
        prices = [(t, 102 if t >= self.start + timedelta(minutes=5) else 100) for t, _ in self.market]
        result = measure(prices, self.market, self.start, self.start + timedelta(hours=1))
        self.assertEqual(result["first_response_minutes"], 5)
        self.assertAlmostEqual(result["returns"]["5"]["excess_return"], .02)
        neutral = measure(prices, prices, self.start, self.start + timedelta(hours=1))
        self.assertEqual(neutral["status"], "no_response_within_window")
        self.assertIsNone(neutral["first_response_minutes"])

    def test_gap_cannot_be_called_slow_response(self):
        prices = [self.market[0], (self.start + timedelta(minutes=30), 105), self.market[-1]]
        result = measure(prices, self.market, self.start, self.start + timedelta(hours=1))
        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertIsNone(result["first_response_minutes"])

    def test_pending_endpoints_never_read_future(self):
        result = measure(self.market, self.market, self.start, self.start + timedelta(minutes=2))
        self.assertEqual(result["returns"]["5"]["status"], "pending")
        self.assertFalse(result["coverage_complete"])

    def test_missing_pre_event_baseline(self):
        result = measure(self.market[1:], self.market, self.start, self.start + timedelta(hours=1))
        self.assertEqual(result["status"], "missing_baseline")

    def test_timezones_required_and_normalized(self):
        self.assertEqual(utc("2026-09-01T10:00:00-04:00"), self.start)
        with self.assertRaises(ValueError):
            utc("2026-09-01T10:00:00")

    def test_import_idempotence_and_atomic_conflict(self):
        data = "ticker,timestamp,price\nMRK,2026-09-01T13:59:00Z,100\n"
        self.assertEqual(import_prices(io.StringIO(data), "fixture"), 1)
        self.assertEqual(import_prices(io.StringIO(data), "fixture"), 0)
        conflict = "ticker,timestamp,price\nSPY,2026-09-01T13:59:00Z,200\nMRK,2026-09-01T13:59:00Z,99\n"
        with self.assertRaises(ValueError):
            import_prices(io.StringIO(conflict), "fixture")
        self.assertEqual(EventPrice.query.count(), 1)
        for price in ("NaN", "Infinity", "0", "-1"):
            with self.assertRaises(ValueError):
                import_prices(io.StringIO(data.replace(",100", "," + price)), "bad")

    def add_event(self):
        article = NewsArticle(identity="a", source_id="test", source_name="Test", feed_url="https://example.com/feed",
            url="https://example.com/news", title="Guidance update", summary="", published_at=self.start,
            retrieved_at=self.start + timedelta(minutes=10))
        db.session.add(article)
        db.session.flush()
        event = NewsEvent(article_id=article.id, ticker="MRK", category="guidance")
        db.session.add(event)
        db.session.commit()
        return event

    def test_clock_and_api_validation(self):
        event = self.add_event()
        for ticker in ("MRK", "SPY"):
            db.session.add_all([EventPrice(ticker=ticker, source="fixture", timestamp=t, price=p) for t, p in self.market])
        db.session.commit()
        result = study(event, "fixture", clock="received", as_of=self.start + timedelta(minutes=12))
        self.assertEqual(result["returns"]["5"]["status"], "pending")
        client = self.app.test_client()
        self.assertEqual(client.get(f"/api/events/{event.id}/response").status_code, 400)
        self.assertEqual(client.get(f"/api/events/{event.id}/response?source=fixture&threshold=nan").status_code, 400)
        self.assertEqual(client.get(f"/api/events/{event.id}/response?source=fixture").status_code, 200)
        report = self.app.test_cli_runner().invoke(args=["event-report", "--ticker", "MRK", "--category", "guidance", "--source", "fixture"])
        self.assertEqual(report.exit_code, 0, report.output)
        self.assertIn('"response_rate": 0.0', report.output)


if __name__ == "__main__":
    unittest.main()
