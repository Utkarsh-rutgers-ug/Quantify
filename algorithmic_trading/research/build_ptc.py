"""Rebuild the 2026-11-19 case from two Yahoo chart JSON downloads (PTC, SPY)."""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
from app import app
from models import NewsArticle, db
from news_model import classify
from event_study import NewsEvent, import_prices, study

TITLE = "PTC Expands FedRAMP Offerings to Help U.S. Federal Agencies and Contractors Modernize Product Development"
URL = "https://www.ptc.com/en/news/2026/ptc-expands-fedramp-offerings"
WIRE = "https://markets.ptc.ft.markitdigital.com/data/announce/detail?dockey=600-202611190956PR_NEWS_USPRX____NE01995-1"
START = datetime(2026, 11, 19, 14, 56)
SOURCE = "Yahoo Finance 1-minute close"

def read_bars(path, ticker):
    raw = json.loads(path.read_text())["chart"]["result"][0]
    if raw["meta"]["symbol"] != ticker or raw["meta"]["dataGranularity"] != "1m":
        raise ValueError(f"Expected {ticker} minute bars")
    bars = {}
    for stamp, price in zip(raw["timestamp"], raw["indicators"]["quote"][0]["close"], strict=True):
        close = datetime.fromtimestamp(stamp + 60, timezone.utc).replace(tzinfo=None)
        if START - timedelta(minutes=1) <= close <= START + timedelta(hours=1) and price is not None:
            bars[close] = price
    return bars

def build(stock_path, spy_path):
    prices = {"PTC": read_bars(stock_path, "PTC"), "SPY": read_bars(spy_path, "SPY")}
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["ticker", "timestamp", "price"])
    for ticker, series in prices.items():
        for stamp, price in series.items():
            writer.writerow([ticker, stamp.isoformat() + "Z", price])
    stream.seek(0)
    import_prices(stream, SOURCE)
    article = NewsArticle(title=TITLE, identity=hashlib.sha256(URL.encode()).hexdigest(), url=URL,
        feed_url=WIRE, source_name="PTC", source_id="ptc", published_at=START, retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(article)
    db.session.flush()
    event = NewsEvent(article_id=article.id, ticker="PTC", category="product announcement")
    db.session.add(event)
    db.session.flush()
    result = study(event, SOURCE)
    result.pop("event_id")
    result.pop("article_id")
    result.update(title=TITLE, wire=WIRE, classification=classify(TITLE), windows=[])
    for minutes, row in result["returns"].items():
        if row["status"] != "observed":
            continue
        end = START + timedelta(minutes=int(minutes))
        window = {"minutes": int(minutes)}
        for ticker, series in prices.items():
            baseline = max(t for t in series if t < START)
            last = max(t for t in series if t <= end)
            change = 100 * (series[last] - series[baseline]) / series[baseline]
            key = "stock_return" if ticker == "PTC" else "benchmark_return"
            assert math.isclose(change, row[key]*100, abs_tol=1e-10)
            window[ticker] = dict(base=series[baseline], close=series[last], end=last.isoformat()+"Z", pct=round(change, 4))
        window["excess_pp"] = round(row["excess_return"]*100, 4)
        result["windows"].append(window)
    result["chart"] = {}
    for ticker, series in prices.items():
        base = series[START - timedelta(minutes=1)]
        result["chart"][ticker] = [
            [minute, round(100 * (series[stamp] / base - 1), 4) if stamp in series else None]
            for minute in range(-1, 61)
            for stamp in [START + timedelta(minutes=minute)]]
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("ptc", "spy", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    with app.app_context():
        args.output.write_text(json.dumps(build(args.ptc,args.spy), indent=2)+"\n")
