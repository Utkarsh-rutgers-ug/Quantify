"""Behavior and query-budget checks for the project-wide maintenance review."""
import io
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy import event
import requests

from app import create_app
from models import db, QuoteSample, Position, Trade, Account
import services
from event_study import import_prices, EventPrice
from news_model import predict
from alpha_vantage_api import get_historical_data, AlphaVantageError


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.user = services.create_user_with_account("Review", "review@example.invalid", 5000)
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_import_is_batched_and_late_conflict_rolls_back(self):
        start = datetime(2026, 1, 1)
        rows = [(start + timedelta(minutes=i)).isoformat()+"Z" for i in range(1000)]
        csv = "ticker,timestamp,price\n" + "".join(f"QQQ,{stamp},100\n" for stamp in rows)
        statements = []
        def record(conn, cursor, statement, params, context, many):
            statements.append(statement)
        event.listen(db.engine, 'before_cursor_execute', record)
        try:
            self.assertEqual(import_prices(io.StringIO(csv), "fixture"), 1000)
        finally:
            event.remove(db.engine, 'before_cursor_execute', record)
        self.assertLessEqual(sum(s.lstrip().upper().startswith('SELECT') for s in statements), 3)
        with self.assertRaises(ValueError):
            import_prices(io.StringIO(csv.replace('QQQ,', 'AAPL,') + f"QQQ,{rows[-1]},99\n"), "fixture")
        self.assertEqual(EventPrice.query.count(), 1000)

    def test_chart_range_is_filtered_in_database(self):
        stamp = datetime.utcnow()
        db.session.add_all([QuoteSample(ticker="QQQ", price=100, timestamp=stamp-timedelta(days=10)),
                            QuoteSample(ticker="QQQ", price=110, timestamp=stamp)])
        db.session.commit()
        captured = []
        import chart_builder
        def build(rows, range_name, now=None):
            captured.extend(rows)
            return chart_builder.build_chart(rows, range_name, now)
        with patch.object(services, 'build_chart', side_effect=build):
            result = services.get_quote_chart("QQQ", "24h")
        self.assertEqual(len(captured), 1)
        self.assertEqual(result['sample_count'], 2)

    def test_equity_replay_and_custom_starting_cash(self):
        start = datetime(2026, 1, 1)
        with patch.object(services, 'latest_close', return_value=100):
            services.submit_trade(self.user.id, "AAPL", "BUY", 2, when=start)
        with patch.object(services, 'latest_close', return_value=50):
            services.submit_trade(self.user.id, "QQQ", "BUY", 4, when=start)
        db.session.add_all([QuoteSample(ticker="AAPL", timestamp=start+timedelta(minutes=1), price=110),
                            QuoteSample(ticker="QQQ", timestamp=start+timedelta(minutes=1), price=45)])
        db.session.commit()
        with patch.object(services, 'latest_close', return_value=120):
            services.submit_trade(self.user.id, "AAPL", "SELL", 1, when=start+timedelta(minutes=2))
        curve = services.build_equity_curve(self.user.id)
        self.assertEqual([round(x, 2) for x in curve.equity], [5000,5000,5000,5020])
        self.assertEqual(services.get_portfolio_summary(self.user.id)['starting_balance'], 5000)

    def test_conflicting_trade_does_not_save_positions(self):
        from sqlalchemy import update
        def concurrent_change(ticker):
            with db.engine.begin() as conn:
                conn.execute(update(Account).where(Account.user_id==self.user.id).values(cash_balance=5001))
            return 100
        with patch.object(services, 'latest_close', side_effect=concurrent_change):
            with self.assertRaisesRegex(ValueError, 'Account changed'):
                services.submit_trade(self.user.id,"QQQ","BUY",1)
        self.assertEqual(Trade.query.count(),0)
        self.assertEqual(Position.query.count(),0)
        self.assertEqual(Account.query.one().cash_balance,5001)

    def test_missing_price_is_not_a_total_loss(self):
        db.session.add(Position(user_id=self.user.id,ticker="QQQ",quantity=1,avg_cost=100))
        db.session.commit()
        data=services.get_portfolio_summary(self.user.id)
        self.assertIsNone(data['total_equity'])
        self.assertIsNone(data['positions'][0]['unrealized_pl'])

    def test_invalid_api_inputs_and_timezone(self):
        for body in [[], {}, {"name":"X","email":"x@y","starting_balance":"NaN"}]:
            self.assertEqual(self.client.post('/api/users',json=body).status_code,400)
        self.assertEqual(self.client.get('/api/trades').status_code,400)
        self.assertEqual(self.client.get(f'/api/performance?user_id={self.user.id}&start=bad').status_code,400)
        self.assertEqual(self.client.get(f'/api/performance?user_id={self.user.id}&start=2026-01-01T00:00:00Z').status_code,200)

    def test_top_two_ties_are_stable(self):
        from news_model import LABELS
        model={'priors':[0.0]*20,'weights':{'earnings':[1.0]*20},'training_id':'test'}
        result=predict(model,'earnings earnings')
        self.assertEqual((result['topic'],result['alternative']),(LABELS[0],LABELS[1]))

    def test_historical_errors_do_not_disclose_keys(self):
        with patch('alpha_vantage_api.requests.get',side_effect=requests.ConnectionError('FAKE-SECRET')):
            with self.assertRaises(AlphaVantageError) as caught:
                get_historical_data('QQQ','FAKE-SECRET')
        self.assertNotIn('FAKE-SECRET',str(caught.exception))


if __name__ == '__main__':
    unittest.main()
