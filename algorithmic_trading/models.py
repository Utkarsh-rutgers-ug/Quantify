"""
models.py
Single source of truth for all database models.

Design notes for the paper-trading simulation:
- Every User has exactly one Account, which holds a virtual cash balance.
- Trade rows are an immutable ledger (what actually happened).
- Position rows are the current holdings derived from that ledger
  (quantity + average cost), kept in sync every time a trade executes.
- HistoricalPrice is just market data cache, unrelated to any user.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index

db = SQLAlchemy()

STARTING_BALANCE = 100_000.00  # default virtual cash for a new account


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship(
        "Account", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    trades = db.relationship("Trade", backref="user", cascade="all, delete-orphan")
    positions = db.relationship("Position", backref="user", cascade="all, delete-orphan")


class Account(db.Model):
    """Virtual brokerage account: just a cash balance for the simulation."""

    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    cash_balance = db.Column(db.Float, nullable=False, default=STARTING_BALANCE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Trade(db.Model):
    """Immutable ledger of every simulated buy/sell."""

    __tablename__ = "trades"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ticker = db.Column(db.String(10), nullable=False)
    side = db.Column(db.String(4), nullable=False)  # BUY or SELL
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    realized_pnl = db.Column(db.Float, nullable=True)  # only set on SELL
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Position(db.Model):
    """Current holdings per user/ticker, kept in sync as trades execute."""

    __tablename__ = "positions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ticker = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    avg_cost = db.Column(db.Float, nullable=False, default=0.0)

    __table_args__ = (
        Index("ix_position_user_ticker", "user_id", "ticker", unique=True),
    )


class HistoricalPrice(db.Model):
    """Cached daily OHLCV data pulled from Alpha Vantage."""

    __tablename__ = "historical_prices"

    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(10), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Integer, nullable=False)

    __table_args__ = (Index("ix_ticker_date", "ticker", "date", unique=True),)


class WatchedTicker(db.Model):
    """A symbol the local sampler should continue tracking."""

    __tablename__ = "watched_tickers"

    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(20), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_sampled_at = db.Column(db.DateTime, nullable=True)


class QuoteSample(db.Model):
    """A locally persisted Finnhub quote snapshot used for charts and trades."""

    __tablename__ = "quote_samples"

    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(20), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)
    open = db.Column(db.Float, nullable=True)
    high = db.Column(db.Float, nullable=True)
    low = db.Column(db.Float, nullable=True)
    previous_close = db.Column(db.Float, nullable=True)

    __table_args__ = (
        Index("ix_quote_sample_ticker_timestamp", "ticker", "timestamp"),
    )
