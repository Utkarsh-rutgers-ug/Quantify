"""Regression tests for risk checks immediately after searching a new symbol."""
import json
import os
import unittest
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import pandas as pd
from app import create_app
from models import db, QuoteSample
import risk_engine


class RiskHistoryTests(unittest.TestCase):
    def test_short_history_has_no_rating(self):
        for days in (1, 4, 5, 20):
            frame = pd.DataFrame({"close": [100.] * days, "high": [101.] * days,
                                  "low": [99.] * days}, index=pd.date_range("2026-01-01", periods=days))
            with self.subTest(days=days), self.assertRaisesRegex(ValueError, "Not enough daily price history"):
                risk_engine.assess(frame, "QQQ")

    def test_complete_history_is_strict_json(self):
        frame = pd.DataFrame({"close": [100.] * 21, "high": [101.] * 21,
                              "low": [99.] * 21}, index=pd.date_range("2026-01-01", periods=21))
        result = risk_engine.assess(frame, "QQQ").to_dict()
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["signal"], "HOLD")

    def test_new_quote_returns_explanation(self):
        app = create_app()
        with app.app_context():
            db.session.add(QuoteSample(ticker="QQQ", timestamp=datetime(2026, 10, 4, 16), price=749.58))
            db.session.commit()
            response = app.test_client().get("/api/risk/QQQ")
            self.assertEqual(response.status_code, 404)
            self.assertIn("1 of 21", response.get_json()["error"])
            self.assertNotIn("NaN", response.get_data(as_text=True))
            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
