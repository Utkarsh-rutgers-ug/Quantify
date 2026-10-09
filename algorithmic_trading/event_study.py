"""Offline news/price alignment. Returns are research labels, never trading signals."""
import csv
import json
import math
import re
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from statistics import median

import click
from flask import Blueprint, request
from sqlalchemy import tuple_, insert
from models import db, NewsArticle


class EventPrice(db.Model):
    __tablename__ = "event_prices"
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(20), nullable=False)
    source = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    price = db.Column(db.Float, nullable=False)
    imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("ticker", "source", "timestamp"),)


class NewsEvent(db.Model):
    __tablename__ = "news_events"
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("news_articles.id"), nullable=False)
    ticker = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    linked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("article_id", "ticker"),)


def utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamps must include a timezone (for example Z).")
    return stamp.astimezone(timezone.utc).replace(tzinfo=None)


def symbol(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", value):
        raise ValueError("Invalid ticker.")
    return value


def import_prices(stream, source):
    """Atomic, idempotent import; conflicting prices require explicit investigation."""
    if not source.strip() or len(source) > 80:
        raise ValueError("A source name of 1–80 characters is required.")
    reader = csv.DictReader(stream)
    if not {"ticker", "timestamp", "price"}.issubset(reader.fieldnames or []):
        raise ValueError("CSV needs ticker,timestamp,price columns.")
    incoming = {}
    try:
        for number, row in enumerate(reader, 2):
            if number > 100001:
                raise ValueError("Import at most 100,000 rows per file.")
            ticker, stamp, price = symbol(row["ticker"]), utc(row["timestamp"]), float(row["price"])
            if not math.isfinite(price) or price <= 0 or stamp > datetime.utcnow():
                raise ValueError(f"Invalid price or future timestamp on row {number}.")
            key = (ticker, stamp)
            if key in incoming and incoming[key] != price:
                raise ValueError(f"Conflicting price on row {number}; nothing imported.")
            incoming[key] = price
        added = 0
        keys = list(incoming)
        # Bound memory/SQL parameters while avoiding 100,000 individual lookups.
        for offset in range(0, len(keys), 400):
            batch = keys[offset:offset + 400]
            existing = {(ticker, stamp): price for ticker, stamp, price in
                db.session.query(EventPrice.ticker, EventPrice.timestamp, EventPrice.price).filter(
                    EventPrice.source == source,
                    tuple_(EventPrice.ticker, EventPrice.timestamp).in_(batch)).all()}
            additions = []
            for ticker, stamp in batch:
                price = incoming[(ticker, stamp)]
                if (ticker, stamp) in existing:
                    if existing[(ticker, stamp)] != price:
                        raise ValueError("Conflicting stored price; nothing imported.")
                else:
                    additions.append({"ticker": ticker, "timestamp": stamp, "source": source, "price": price})
            if additions:
                db.session.execute(insert(EventPrice), additions)
                added += len(additions)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return added


def measure(stock, benchmark, start, as_of, threshold=0.01):
    """Compare observed prices over 60 elapsed minutes; never bridge closed sessions.

    Inputs are sorted (UTC datetime, price) pairs. Require observations at least
    every 90 seconds and baseline/endpoint prices no more than 60 seconds old.
    A crossing time is the first *observed* crossing, not the exact market time.
    """
    end = start + timedelta(minutes=60)
    points = {"stock": stock, "benchmark": benchmark}
    times = {key: [t for t, _ in rows] for key, rows in points.items()}

    def at(key, time, strict=False):
        index = bisect_right(times[key], time - timedelta(microseconds=1) if strict else time) - 1
        if index < 0 or (time - times[key][index]).total_seconds() > 60:
            return None
        return points[key][index][1]

    result = {"status": "pending", "returns": {}, "first_response_minutes": None,
              "threshold": threshold, "horizon_minutes": 60, "clock": "elapsed_minutes",
              "coverage_complete": False}
    if start > as_of:
        return result
    base_stock, base_bench = at("stock", start, True), at("benchmark", start, True)
    if base_stock is None or base_bench is None:
        return dict(result, status="missing_baseline")
    stop = min(end, as_of)
    for minutes in (1, 5, 15, 60):
        target = start + timedelta(minutes=minutes)
        if target > as_of:
            result["returns"][str(minutes)] = {"status": "pending"}
            continue
        price, bench = at("stock", target), at("benchmark", target)
        # A pre-event observation cannot stand in for a post-event endpoint.
        if (price is None or bench is None or
                not any(start < t <= target for t in times["stock"]) or
                not any(start < t <= target for t in times["benchmark"])):
            result["returns"][str(minutes)] = {"status": "missing"}
        else:
            raw, market = price / base_stock - 1, bench / base_bench - 1
            result["returns"][str(minutes)] = {
                "status": "observed", "stock_return": raw,
                "benchmark_return": market, "excess_return": raw - market}
    # Both series must continuously cover the full observed interval. Gaps mean
    # the true first crossing is unknown, even if a later large move is visible.
    covered = True
    for key in points:
        stamps = [t for t in times[key] if start <= t <= stop]
        edges = [start] + stamps + [stop]
        if any((b - a).total_seconds() > 90 for a, b in zip(edges, edges[1:])):
            covered = False
    if not covered:
        return dict(result, status="insufficient_coverage")
    for stamp, price in stock:
        if not start < stamp <= stop:
            continue
        bench = at("benchmark", stamp)
        if bench is None:
            return dict(result, status="insufficient_coverage")
        excess = price / base_stock - bench / base_bench
        if abs(excess) >= threshold:
            result["first_response_minutes"] = (stamp - start).total_seconds() / 60
            result["response_direction"] = "up" if excess > 0 else "down"
            break
    complete = as_of >= end and all(v["status"] == "observed" for v in result["returns"].values())
    result["coverage_complete"] = complete
    result["status"] = ("insufficient_coverage" if as_of >= end and not complete else
                        "responded" if result["first_response_minutes"] is not None else
                        "no_response_within_window" if complete else "pending")
    return result


def study(event, source, benchmark="SPY", threshold=0.01, clock="published", as_of=None):
    if clock not in ("published", "received"):
        raise ValueError("clock must be published or received.")
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("threshold must be a fraction greater than 0 and at most 1.")
    benchmark = symbol(benchmark)
    if benchmark == event.ticker:
        raise ValueError("Benchmark must differ from the event ticker.")
    article = db.session.get(NewsArticle, event.article_id)
    start = article.published_at if clock == "published" else article.retrieved_at
    info = {"event_id": event.id, "article_id": article.id, "ticker": event.ticker,
            "category": event.category, "source_url": article.url, "price_source": source,
            "benchmark": benchmark, "event_clock": clock,
            "published_at": article.published_at.isoformat() + "Z" if article.published_at else None,
            "received_at": article.retrieved_at.isoformat() + "Z",
            "research_only": True, "method": "excess-return-v1"}
    if start is None:
        return dict(info, status="missing_publication_time")
    as_of = as_of or datetime.utcnow()
    rows = EventPrice.query.filter(EventPrice.source == source,
        EventPrice.ticker.in_([event.ticker, benchmark]),
        EventPrice.timestamp >= start - timedelta(seconds=60),
        EventPrice.timestamp <= min(as_of, start + timedelta(minutes=60))
    ).order_by(EventPrice.timestamp).all()
    stock = [(r.timestamp, r.price) for r in rows if r.ticker == event.ticker]
    market = [(r.timestamp, r.price) for r in rows if r.ticker == benchmark]
    return dict(info, **measure(stock, market, start, as_of, threshold))


def register(app):
    api = Blueprint("event_study", __name__)

    @api.get("/api/events/<int:event_id>/response")
    def response(event_id):
        event = db.session.get(NewsEvent, event_id)
        if event is None:
            return {"error": "Event not found."}, 404
        source = request.args.get("source", "").strip()
        if not source:
            return {"error": "Specify the price source."}, 400
        try:
            return study(event, source, request.args.get("benchmark", "SPY"),
                         float(request.args.get("threshold", "0.01")),
                         request.args.get("clock", "published"))
        except ValueError as exc:
            return {"error": str(exc)}, 400

    app.register_blueprint(api)

    @app.cli.command("event-prices-import")
    @click.argument("path", type=click.File("r"))
    @click.option("--source", required=True)
    def prices_import(path, source):
        """Import permitted intraday observations with actual UTC market timestamps."""
        try:
            click.echo(f"Imported {import_prices(path, source)} prices.")
        except (ValueError, KeyError, TypeError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("event-link")
    @click.argument("article_id", type=int)
    @click.argument("ticker")
    @click.option("--category", required=True)
    def event_link(article_id, ticker, category):
        """Link an existing news article to a reviewed company and event category."""
        try:
            ticker = symbol(ticker)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if db.session.get(NewsArticle, article_id) is None:
            raise click.ClickException("Article not found.")
        if not category.strip() or len(category) > 80:
            raise click.ClickException("Category must contain 1–80 characters.")
        event = NewsEvent.query.filter_by(article_id=article_id, ticker=ticker).first()
        if event and event.category != category:
            raise click.ClickException("Existing category differs; review the existing event.")
        if event is None:
            event = NewsEvent(article_id=article_id, ticker=ticker, category=category)
            db.session.add(event)
            db.session.commit()
        click.echo(f"Event {event.id}")

    @app.cli.command("event-report")
    @click.option("--ticker", required=True)
    @click.option("--category", required=True)
    @click.option("--source", required=True)
    @click.option("--benchmark", default="SPY")
    @click.option("--threshold", type=float, default=0.01)
    def report(ticker, category, source, benchmark, threshold):
        """JSON report: outcomes and descriptive monthly response-time comparisons."""
        try:
            events = NewsEvent.query.filter_by(ticker=symbol(ticker), category=category).order_by(NewsEvent.id).all()
            rows = [study(e, source, benchmark, threshold) for e in events]
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        months = {}
        for row in rows:
            month = (row["published_at"] or "unknown")[:7]
            bucket = months.setdefault(month, {"events": 0, "complete": 0, "responded": 0, "delays": []})
            bucket["events"] += 1
            if row.get("coverage_complete"):
                bucket["complete"] += 1
                if row["first_response_minutes"] is not None:
                    bucket["responded"] += 1
                    bucket["delays"].append(row["first_response_minutes"])
        for bucket in months.values():
            delays = bucket.pop("delays")
            bucket["median_minutes_among_responders"] = median(delays) if delays else None
            bucket["response_rate"] = bucket["responded"] / bucket["complete"] if bucket["complete"] else None
        click.echo(json.dumps({"events": rows, "months": months,
            "interpretation": "Descriptive only; changing event mix and missing data can change medians. "
                              "No-response events remain in response-rate denominators. "
                              "Returns are future labels, never prediction-time features."}, indent=2))
