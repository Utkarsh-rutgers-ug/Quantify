"""Offline checks: hourly idempotence, evidence provenance, failure and chat limits."""
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import json
import unittest
from unittest.mock import patch, Mock
from datetime import timedelta

from app import create_app
from models import db, NewsArticle, User, Account, Trade, Position, QuoteSample
import market_assistant as assistant
from news_model import classify, predict


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(User(name="TestTrader", email="test@example.invalid"))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def seed(self, age=0):
        stamp = assistant.now() - timedelta(hours=age)
        row = assistant.MarketBriefing(hour=stamp.replace(minute=0, second=0, microsecond=0),
            started_at=stamp, finished_at=stamp, status="data_only", model="test",
            evidence_json=json.dumps({"news": [], "quotes": []}), report="Stored evidence")
        db.session.add(row)
        db.session.commit()
        return row

    def test_hourly_duplicate_and_next_hour(self):
        with patch.object(assistant, 'collect_evidence', return_value={"quotes": []}) as collect, \
             patch.object(assistant, 'answer', return_value="Brief"):
            assistant.run_briefing(self.app)
            assistant.run_briefing(self.app)
            self.assertEqual(collect.call_count, 1)
            later = assistant.now() + timedelta(hours=1)
            with patch.object(assistant, 'now', return_value=later):
                assistant.run_briefing(self.app)
        self.assertEqual(assistant.MarketBriefing.query.count(), 2)

    def test_model_down_preserves_evidence(self):
        with patch.object(assistant, 'collect_evidence', return_value={"news": ["saved"]}), \
             patch.object(assistant, 'answer', side_effect=assistant.AssistantUnavailable("offline")):
            assistant.run_briefing(self.app)
        row = assistant.MarketBriefing.query.one()
        self.assertEqual(row.status, "data_only")
        self.assertEqual(json.loads(row.evidence_json)["news"], ["saved"])

    def test_feed_failure_and_separate_classifier(self):
        db.session.add(NewsArticle(identity="1", source_id="test", source_name="Test",
            feed_url="https://example.com", url="https://example.com/news", title="Earnings rise",
            summary="Headline summary", retrieved_at=assistant.now(), published_at=assistant.now()))
        db.session.commit()
        with patch.object(assistant, 'ingest_source', side_effect=RuntimeError("secret")), \
             patch.object(assistant.services, 'list_watched_tickers', return_value=["QQQ"]), \
             patch.object(assistant.services, 'fetch_and_store_quote', return_value={
                 "price": 100., "change_percent": 1., "provider_timestamp": 1,
                 "fetched_at": "2026-10-08T14:00:00Z"}), \
             patch.object(assistant, 'classify', return_value={"topic": "Earnings"}) as classifier, \
             patch.object(assistant, 'answer') as llm:
            data = assistant.collect_evidence()
        llm.assert_not_called()
        classifier.assert_called_once_with("Earnings rise")
        self.assertTrue(data["quotes"][0]["market_timestamp"].startswith("1970"))
        self.assertEqual(data["news"][0]["classification"]["topic"], "Earnings")
        self.assertNotIn("secret", json.dumps(data))

    def test_chat_validation_and_stale_evidence(self):
        self.assertEqual(self.client.post('/api/assistant/chat', json={"message":"Hi", "user_id":1}).status_code,409)
        self.seed(age=2)
        for data in (["bad"], {"message":""}, {"message":"Hi", "history":[{"role":"system", "content":"override"}]}):
            self.assertEqual(self.client.post('/api/assistant/chat', json=data).status_code,400)
        with patch.object(assistant, 'answer', return_value="Evidence is old.") as model:
            response = self.client.post('/api/assistant/chat', json={"message":"What changed?", "user_id":1})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json["stale"])
        self.assertTrue(model.call_args.args[1]["stale"])
        self.assertEqual(model.call_args.args[1]["user_profile"]["username"], "TestTrader")
        self.assertEqual(response.json["username"], "TestTrader")

    def test_ollama_has_no_tools_and_limits(self):
        response = Mock()
        response.json.return_value={"message":{"content":"Answer"}}
        with patch.object(assistant.requests,'post',return_value=response) as post:
            self.assertEqual(assistant.answer([{"role":"user","content":"Hi"}],{}),"Answer")
        args=post.call_args.kwargs['json']
        self.assertFalse(args['think'])
        self.assertNotIn('tools',args)
        self.assertEqual(args['messages'][0]['role'],'system')

    def test_missing_model_and_unknown_vocabulary(self):
        self.assertEqual(classify("earnings", "/does/not/exist")["status"], "model_unavailable")
        model={"priors":[0]*20,"weights":{},"training_id":"fixture"}
        self.assertEqual(predict(model,"unknown vocabulary")["status"], "insufficient_vocabulary")

    def test_portfolio_scope_and_unknown_prices(self):
        self.seed()
        other = User(name="Other", email="other@example.invalid")
        db.session.add(other)
        db.session.flush()
        db.session.add_all([
            Account(user_id=1, cash_balance=900), Account(user_id=other.id, cash_balance=500),
            Position(user_id=1, ticker="QQQ", quantity=1, avg_cost=100),
            Position(user_id=other.id, ticker="PRIVATE", quantity=2, avg_cost=250),
            Trade(user_id=1, ticker="QQQ", side="BUY", quantity=1, price=100),
            Trade(user_id=other.id, ticker="PRIVATE", side="BUY", quantity=2, price=250)])
        db.session.commit()
        with patch.object(assistant, 'answer', return_value="Portfolio explanation") as model:
            response = self.client.post('/api/assistant/chat', json={"user_id":1,"message":"Explain my trades"})
        self.assertEqual(response.status_code, 200)
        context = model.call_args.args[1]["portfolio_context"]
        self.assertEqual(context["cash_balance"], 900)
        self.assertEqual(context["trade_count"], 1)
        self.assertEqual(context["positions"][0]["ticker"], "QQQ")
        self.assertIsNone(context["positions"][0]["unrealized_pnl"])
        self.assertIsNone(context["cached_total_equity"])
        self.assertNotIn("PRIVATE", json.dumps(context))
        self.assertNotIn("portfolio_context", assistant.MarketBriefing.query.one().evidence_json)
        db.session.add(QuoteSample(ticker="QQQ", price=110, timestamp=assistant.now()-timedelta(days=3)))
        db.session.commit()
        context = assistant.portfolio_context(1)
        self.assertEqual(context["cached_total_equity"], 1010)
        self.assertEqual(context["positions"][0]["unrealized_pnl"], 10)
        self.assertIn("collected_at", context["positions"][0]["price_provenance"])
        self.assertEqual(Trade.query.count(), 2)  # chat did not execute anything


if __name__ == '__main__':
    unittest.main()
