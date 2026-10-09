"""Offline feed parsing, provenance, deduplication, and API tests."""
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["FINNHUB_API_KEY"] = "offline-test-token"

import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from app import create_app
from models import db, NewsArticle
from news import parse_feed, ingest_source, classify_mentions, fetch_feed, NewsError, MAX_BYTES

RSS = b'''<rss version="2.0"><channel>
<item><title>Jim Cramer discusses Merck &amp; Co.</title>
<link>https://www.cnbc.com/2026/09/25/example.html?utm_source=test</link>
<description><![CDATA[<p>MRK <b>research</b> update.</p><script>bad()</script>]]></description>
<pubDate>Fri, 25 Sep 2026 08:00:00 -0400</pubDate></item>
<item><title>Merck outlook</title><link>https://www.cnbc.com/ambiguous.html</link></item>
<item><title>Merck KGaA reports</title><link>https://www.cnbc.com/germany.html</link>
<pubDate>invalid date</pubDate></item>
<item><title>Unsafe</title><link>javascript:alert(1)</link></item>
<item><title>Missing link</title></item>
</channel></rss>'''


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_rss_dates_plain_text_and_invalid_links(self):
        rows, skipped = parse_feed(RSS, "cnbc-top")
        self.assertEqual(len(rows), 3)
        self.assertEqual(skipped, 2)
        self.assertEqual(rows[0]["published_at"], datetime(2026, 9, 25, 12))
        self.assertEqual(rows[0]["summary"], "MRK research update.")
        self.assertEqual(rows[0]["url"], "https://www.cnbc.com/2026/09/25/example.html")
        self.assertTrue(rows[0]["cramer_mention"])
        self.assertEqual(rows[0]["mrk_match"], "explicit")
        self.assertEqual(rows[1]["mrk_match"], "ambiguous")
        self.assertIsNone(rows[2]["mrk_match"])
        self.assertIsNone(rows[2]["published_at"])

    def test_atom_and_missing_timezone(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>BBC business</title><link rel="self" href="https://example.invalid"/>
        <link rel="alternate" href="https://www.bbc.com/news/a"/>
        <published>2026-09-25T12:30:00Z</published><summary>A summary.</summary>
        </entry></feed>'''
        rows, skipped = parse_feed(xml, "bbc-business")
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]["published_at"], datetime(2026, 9, 25, 12, 30))
        rows, _ = parse_feed(xml.replace(b"12:30:00Z", b"12:30:00"), "bbc-business")
        self.assertIsNone(rows[0]["published_at"])

    def test_untrusted_xml_and_size_limits(self):
        malicious = '<!DOCTYPE rss [<!ENTITY secret "expanded">]><rss><channel><item><title>&secret;</title></item></channel></rss>'
        for payload in [b"<broken", b"<html/>", malicious.encode(), malicious.encode("utf-16"), b"x" * (MAX_BYTES+1)]:
            with self.subTest(size=len(payload)), self.assertRaises(NewsError):
                parse_feed(payload, "cnbc-top")

    def test_canonical_duplicates_preserve_first_observation(self):
        first = ingest_source("cnbc-top", RSS)
        original = NewsArticle.query.order_by(NewsArticle.id).first()
        title, observed = original.title, original.retrieved_at
        second = ingest_source("cnbc-top", RSS.replace(b"utm_source=test", b"utm_source=changed").replace(b"discusses", b"revises"))
        self.assertEqual(first["inserted"], 3)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["duplicates"], 3)
        self.assertEqual(NewsArticle.query.count(), 3)
        self.assertEqual(original.title, title)
        self.assertEqual(original.retrieved_at, observed)

    def test_entity_disambiguation(self):
        for text, match in [("Merck & Co. results", "explicit"), ("MRK rises", "explicit"),
                            ("Keytruda study", "explicit"), ("Merck raises guidance", "ambiguous"),
                            ("Merck KGaA", None), ("Merck Group in Darmstadt", None), ("Other stock", None)]:
            with self.subTest(text=text):
                self.assertEqual(classify_mentions(text, "")[0], match)

    def test_api_filters_pagination_and_no_implicit_fetch(self):
        client = self.app.test_client()
        with patch("news.fetch_feed", side_effect=AssertionError("GET must not collect news")):
            self.assertEqual(client.get("/api/news").json["articles"], [])
            ingest_source("cnbc-top", RSS)
            first = client.get("/api/news?limit=2").json
            second = client.get(f"/api/news?limit=2&before_id={first['next_before_id']}").json
            self.assertEqual(len(second["articles"]), 1)
            self.assertEqual(len(client.get("/api/news?ticker=MRK").json["articles"]), 2)
            cramer = client.get("/api/news?ticker=MRK&person=jim-cramer").json["articles"]
            self.assertEqual(len(cramer), 1)
            self.assertIsNone(cramer[0]["expected_impact"])
            self.assertTrue(cramer[0]["published_at"].endswith("Z"))
            self.assertEqual(len(client.get("/api/news/sources").json["sources"]), 2)
        for query in ["limit=0", "limit=101", "limit=bad", "before_id=-1", "ticker=AAPL", "source=unknown", "person=unknown"]:
            self.assertEqual(client.get("/api/news?" + query).status_code, 400)

    def test_feed_failure_does_not_stop_other_source(self):
        with patch("news.fetch_feed", side_effect=[NewsError("Unavailable"), RSS]):
            result = self.app.test_cli_runner().invoke(args=["news-fetch"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("bbc-business: Unavailable", result.output)
        self.assertEqual(NewsArticle.query.count(), 3)

    def test_fetch_rejects_redirects_and_oversized_responses(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status_code = 302
        with patch("news.requests.get", return_value=response) as get:
            with self.assertRaises(NewsError):
                fetch_feed("cnbc-top")
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
        response.status_code = 200
        response.iter_content.return_value = [b"x" * (MAX_BYTES+1)]
        with patch("news.requests.get", return_value=response), self.assertRaises(NewsError):
            fetch_feed("cnbc-top")


if __name__ == "__main__":
    unittest.main()
