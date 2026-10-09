"""
services.py
Business logic for the paper-trading simulation:
  - account creation / virtual cash
  - executing BUY/SELL trades against that cash balance (no real money, ever)
  - keeping Position rows in sync
  - equity curve + performance summary
  - wiring price history into risk_engine for per-position risk/signal output
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import math
from heapq import merge
from itertools import groupby
import re
import pandas as pd
from flask import current_app

from models import (
    db, User, Account, Trade, Position, HistoricalPrice, QuoteSample, WatchedTicker,
    STARTING_BALANCE,
)
from alpha_vantage_api import get_historical_data
from finnhub_api import get_quote, search_symbols
from chart_builder import build_chart, RANGE_CONFIG
import risk_engine

# ---------------------------------------------------------------------------
# Account / user setup
# ---------------------------------------------------------------------------

def create_user_with_account(name: str, email: str, starting_balance: float = STARTING_BALANCE) -> User:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Name must contain 1–80 characters")
    if not isinstance(email, str) or not 1 <= len(email.strip()) <= 120:
        raise ValueError("Email must contain 1–120 characters")
    if isinstance(starting_balance, bool):
        raise ValueError("Starting balance must be a finite positive number")
    try:
        starting_balance = float(starting_balance)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Starting balance must be a finite positive number") from None
    if not math.isfinite(starting_balance) or starting_balance <= 0:
        raise ValueError("Starting balance must be a finite positive number")
    name, email = name.strip(), email.strip()
    user = User(name=name, email=email)
    db.session.add(user)
    db.session.flush()  # assign user.id without committing yet

    account = Account(user_id=user.id, cash_balance=starting_balance)
    db.session.add(account)
    db.session.commit()
    return user


def get_account(user_id: int) -> Account:
    account = Account.query.filter_by(user_id=user_id).one_or_none()
    if account is None:
        raise ValueError(f"No account found for user_id={user_id}")
    return account


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def upsert_prices(ticker: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    # Fetch once instead of issuing one SELECT for every incoming daily row.
    existing = {p.date: p for p in HistoricalPrice.query.filter(
        HistoricalPrice.ticker == ticker,
        HistoricalPrice.date >= df.index.min().date(),
        HistoricalPrice.date <= df.index.max().date()).all()}
    inserted = 0
    for d, row in df.iterrows():
        hp = existing.get(d.date())
        if hp is None:
            hp = HistoricalPrice(
                ticker=ticker,
                date=d.date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]) if not pd.isna(row["volume"]) else 0,
            )
            db.session.add(hp)
            existing[d.date()] = hp
            inserted += 1
        else:
            hp.open = float(row["open"])
            hp.high = float(row["high"])
            hp.low = float(row["low"])
            hp.close = float(row["close"])
            hp.volume = int(row["volume"]) if not pd.isna(row["volume"]) else 0
    db.session.commit()
    return inserted


def fetch_and_store_prices(ticker: str, interval: str = "daily", output_size: str = "compact") -> int:
    api_key = current_app.config.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY not configured. Set it as an environment variable.")
    df = get_historical_data(ticker, api_key, interval=interval, output_size=output_size)
    return upsert_prices(ticker, df)


def get_price_history(ticker: str) -> pd.DataFrame:
    """Pull cached price history out of the DB as a DataFrame for risk_engine."""
    rows = (
        HistoricalPrice.query.filter_by(ticker=ticker)
        .order_by(HistoricalPrice.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
    ).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


def latest_close(ticker: str) -> Optional[float]:
    sample = (
        QuoteSample.query.filter_by(ticker=ticker.upper())
        .order_by(QuoteSample.timestamp.desc())
        .first()
    )
    if sample:
        return float(sample.price)
    hp = (
        HistoricalPrice.query.filter_by(ticker=ticker)
        .order_by(HistoricalPrice.date.desc())
        .first()
    )
    return float(hp.close) if hp else None


def watch_ticker(ticker: str) -> WatchedTicker:
    ticker = ticker.strip().upper()
    watched = WatchedTicker.query.filter_by(ticker=ticker).one_or_none()
    if watched is None:
        watched = WatchedTicker(ticker=ticker)
        db.session.add(watched)
    return watched


def list_watched_tickers() -> List[str]:
    return [row.ticker for row in WatchedTicker.query.order_by(WatchedTicker.ticker).all()]


def fetch_and_store_quote(ticker: str) -> Dict:
    ticker = ticker.strip().upper()
    token = current_app.config.get("FINNHUB_API_KEY", "")
    quote = get_quote(ticker, token)
    watched = watch_ticker(ticker)
    sample = QuoteSample(
        ticker=ticker,
        timestamp=quote.fetched_at,
        price=quote.price,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        previous_close=quote.previous_close,
    )
    watched.last_sampled_at = quote.fetched_at
    db.session.add(sample)
    db.session.commit()
    result = quote.to_dict()
    result["sample_id"] = sample.id
    return result


def latest_quote(ticker: str) -> Optional[Dict]:
    sample = (
        QuoteSample.query.filter_by(ticker=ticker.strip().upper())
        .order_by(QuoteSample.timestamp.desc())
        .first()
    )
    if sample is None:
        return None
    change = (
        sample.price - sample.previous_close
        if sample.previous_close not in (None, 0)
        else 0.0
    )
    change_percent = (
        change / sample.previous_close * 100
        if sample.previous_close not in (None, 0)
        else 0.0
    )
    return {
        "ticker": sample.ticker,
        "price": sample.price,
        "open": sample.open,
        "high": sample.high,
        "low": sample.low,
        "previous_close": sample.previous_close,
        "change": round(change, 4),
        "change_percent": round(change_percent, 4),
        "fetched_at": sample.timestamp.isoformat() + "Z",
    }


def search_market_symbols(query: str) -> List[Dict]:
    token = current_app.config.get("FINNHUB_API_KEY", "")
    return search_symbols(query, token)


def get_quote_chart(ticker: str, range_name: str) -> Dict:
    if range_name not in RANGE_CONFIG:
        raise ValueError("range must be one of: 24h, 1w, 1m, 1y, all")
    ticker = ticker.strip().upper()
    watch_ticker(ticker)
    db.session.commit()
    query = QuoteSample.query.filter_by(ticker=ticker)
    total = query.count()
    stamp = datetime.utcnow()
    lookback = RANGE_CONFIG[range_name]["lookback"]
    if lookback is not None:
        query = query.filter(QuoteSample.timestamp >= stamp - lookback)
    rows = query.order_by(QuoteSample.timestamp.asc()).all()
    result = build_chart(rows, range_name, now=stamp)
    result["ticker"] = ticker
    result["sample_count"] = total
    return result


# ---------------------------------------------------------------------------
# Paper trading: this is the core of the simulation.
# Every trade moves virtual cash in Account and updates Position.
# No real brokerage, no real money, ever.
# ---------------------------------------------------------------------------

def submit_trade(
    user_id: int,
    ticker: str,
    side: str,
    quantity: int,
    when: Optional[datetime] = None,
) -> Dict:
    if type(user_id) is not int or not 0 < user_id <= 2_147_483_647:
        raise ValueError("user_id must be a positive integer")
    if type(quantity) is not int or not 0 < quantity <= 2_147_483_647:
        raise ValueError("quantity must be a positive whole number within the supported range")
    if not isinstance(ticker, str):
        raise ValueError("ticker must be a symbol string")
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
        raise ValueError("ticker must be 1–10 letters, digits, dots, or hyphens, starting with a letter")
    if not isinstance(side, str):
        raise ValueError("side must be BUY or SELL")
    side = side.strip().upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    when = when or datetime.utcnow()
    account = get_account(user_id)

    # Execution price always comes from server-held market data.
    price = latest_close(ticker)
    if price is None:
        price = fetch_and_store_quote(ticker)["price"]
    try:
        price = float(price)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Market price must be finite and greater than zero") from None
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Market price must be finite and greater than zero")
    if not math.isfinite(price * quantity):
        raise ValueError("Trade value exceeds the supported range")
    if not math.isfinite(account.cash_balance) or not math.isfinite(account.cash_balance + price * quantity):
        raise ValueError("Account balance exceeds the supported range")
    previous_cash = account.cash_balance
    position = Position.query.filter_by(user_id=user_id, ticker=ticker).one_or_none()
    if side == "BUY" and (position.quantity if position else 0) + quantity > 2_147_483_647:
        raise ValueError("Position quantity exceeds the supported range")

    realized_pnl = None

    if side == "BUY":
        cost = price * quantity
        if cost > account.cash_balance:
            raise ValueError(
                f"Insufficient virtual cash: trade costs {cost:.2f}, "
                f"available balance is {account.cash_balance:.2f}"
            )
        account.cash_balance -= cost

        if position is None:
            position = Position(user_id=user_id, ticker=ticker, quantity=0, avg_cost=0.0)
            db.session.add(position)

        # weighted-average cost basis
        new_qty = position.quantity + quantity
        position.avg_cost = (
            (position.avg_cost * position.quantity) + (price * quantity)
        ) / new_qty
        position.quantity = new_qty

    else:  # SELL
        if position is None or position.quantity < quantity:
            held = position.quantity if position else 0
            raise ValueError(
                f"Cannot sell {quantity} shares of {ticker}; only {held} held in the simulation"
            )
        proceeds = price * quantity
        realized_pnl = (price - position.avg_cost) * quantity

        account.cash_balance += proceeds
        position.quantity -= quantity
        # avg_cost stays the same for any remaining shares; reset to 0 if fully closed
        if position.quantity == 0:
            position.avg_cost = 0.0

    trade = Trade(
        user_id=user_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        realized_pnl=realized_pnl,
        timestamp=when,
    )
    # Compare-and-set cash before flushing positions to reject an order whose
    # observed balance changed while it was being prepared.
    from sqlalchemy import update
    with db.session.no_autoflush:
        changed = db.session.execute(update(Account).where(
            Account.id == account.id, Account.cash_balance == previous_cash
        ).values(cash_balance=account.cash_balance).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.session.rollback()
        raise ValueError("Account changed during this trade. Refresh and try again.")
    db.session.expire(account, ["cash_balance"])
    db.session.add(trade)
    db.session.commit()

    return {
        "trade_id": trade.id,
        "ticker": trade.ticker,
        "side": trade.side,
        "quantity": trade.quantity,
        "price": trade.price,
        "realized_pnl": round(realized_pnl, 2) if realized_pnl is not None else None,
        "cash_balance": round(account.cash_balance, 2),
    }


def get_positions(user_id: int) -> List[Dict]:
    """Current open positions with live valuation against cached prices."""
    rows = Position.query.filter_by(user_id=user_id).all()
    result = []
    for p in rows:
        if p.quantity == 0:
            continue
        last_close = latest_close(p.ticker)
        market_value = p.quantity * last_close if last_close is not None else None
        unrealized_pl = (last_close - p.avg_cost) * p.quantity if last_close is not None else None
        result.append(
            {
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avg_cost": round(p.avg_cost, 4),
                "last_price": round(last_close, 4) if last_close is not None else None,
                "market_value": round(market_value, 2) if market_value is not None else None,
                "unrealized_pl": round(unrealized_pl, 2) if unrealized_pl is not None else None,
            }
        )
    return result


def get_portfolio_summary(user_id: int) -> Dict:
    account = get_account(user_id)
    positions = get_positions(user_id)
    complete = all(p["market_value"] is not None for p in positions)
    invested_value = sum(p["market_value"] for p in positions) if complete else None
    total_equity = account.cash_balance + invested_value if complete else None
    return {
        "starting_balance": initial_balance(user_id, account.cash_balance),
        "cash_balance": round(account.cash_balance, 2),
        "invested_value": round(invested_value, 2) if complete else None,
        "total_equity": round(total_equity, 2) if complete else None,
        "valuation_complete": complete,
        "positions": positions,
    }


def initial_balance(user_id, cash_balance):
    """Infer initial cash from this account's ledger without loading trade objects."""
    from sqlalchemy import case, func
    net_spend = db.session.query(func.sum(case(
        (Trade.side == "BUY", Trade.price * Trade.quantity),
        else_=-Trade.price * Trade.quantity))).filter(Trade.user_id == user_id).scalar() or 0
    return round(cash_balance + net_spend, 2)


# ---------------------------------------------------------------------------
# Equity curve / performance (uses realized + unrealized trade history)
# ---------------------------------------------------------------------------

def build_equity_curve(user_id: int, start: Optional[datetime] = None) -> pd.DataFrame:
    """Replay every trade and quote sample into one combined account-equity line."""
    trades = (
        Trade.query.filter_by(user_id=user_id).order_by(Trade.timestamp.asc()).all()
    )
    account = get_account(user_id)
    if not trades:
        return pd.DataFrame({"timestamp": [], "equity": []})

    symbols = sorted({t.ticker for t in trades})
    first_trade_at = trades[0].timestamp

    # Infer the account's original cash from its current cash and full ledger.
    # This also supports users created with a non-default starting balance.
    starting_cash = float(account.cash_balance)
    for t in trades:
        amount = float(t.price) * t.quantity
        starting_cash += amount if t.side == "BUY" else -amount

    samples = (
        QuoteSample.query.filter(
            QuoteSample.ticker.in_(symbols),
            QuoteSample.timestamp >= first_trade_at,
        )
        .order_by(QuoteSample.timestamp.asc())
        .all()
    )

    # Both queries are chronological. Merge them in linear time without building
    # and sorting a second dictionary of the entire quote history.
    changes = merge(
        ((row.timestamp, 0, row) for row in samples),
        ((row.timestamp, 1, row) for row in trades),
        key=lambda change: change[:2],
    )
    running_cash = starting_cash
    invested_value = 0.0
    quantities = {symbol: 0 for symbol in symbols}
    last_prices = {}
    points = [{"timestamp": first_trade_at - timedelta(microseconds=1), "equity": starting_cash}]
    for timestamp, updates in groupby(changes, key=lambda change: change[0]):
        # Each quote/trade is visited once. Samples precede trades at equal times.
        for _, kind, row in updates:
            price = float(row.price)
            invested_value += quantities[row.ticker] * (price - last_prices.get(row.ticker, 0.0))
            last_prices[row.ticker] = price
            if kind == 1:
                quantity = row.quantity if row.side == "BUY" else -row.quantity
                amount = price * quantity
                running_cash -= amount
                quantities[row.ticker] += quantity
                invested_value += amount
        points.append({"timestamp": timestamp, "equity": running_cash + invested_value})

    curve = pd.DataFrame(points)
    if start is not None:
        start_at = pd.to_datetime(start)
        curve = curve[curve["timestamp"] >= start_at]
    return curve


def performance_summary(curve: pd.DataFrame) -> Dict:
    if curve.empty:
        return {"equity_start": 0, "equity_end": 0, "gain_abs": 0, "gain_pct": 0}
    start_val = float(curve["equity"].iloc[0])
    end_val = float(curve["equity"].iloc[-1])
    gain_abs = end_val - start_val
    gain_pct = (gain_abs / start_val * 100.0) if start_val != 0 else 0.0
    return {
        "equity_start": round(start_val, 2),
        "equity_end": round(end_val, 2),
        "gain_abs": round(gain_abs, 2),
        "gain_pct": round(gain_pct, 2),
    }


# ---------------------------------------------------------------------------
# Risk advisor: wires risk_engine.py into live positions for this user
# ---------------------------------------------------------------------------

def assess_ticker_risk(ticker: str) -> Dict:
    df = get_price_history(ticker)
    if df.empty:
        from sqlalchemy import func
        recent_dates = db.session.query(func.date(QuoteSample.timestamp)).filter(
            QuoteSample.ticker == ticker.upper()).distinct().order_by(
                func.date(QuoteSample.timestamp).desc()).limit(21).all()
        cutoff = datetime.fromisoformat(str(recent_dates[-1][0])) if recent_dates else datetime.max
        samples = (
            QuoteSample.query.filter(QuoteSample.ticker == ticker.upper(), QuoteSample.timestamp >= cutoff)
            .order_by(QuoteSample.timestamp.asc())
            .all()
        )
        if samples:
            raw = pd.DataFrame(
                {
                    "timestamp": [s.timestamp for s in samples],
                    "price": [s.price for s in samples],
                    "high": [s.high or s.price for s in samples],
                    "low": [s.low or s.price for s in samples],
                }
            ).set_index("timestamp")
            daily = raw.resample("1D").agg(
                open=("price", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("price", "last"),
            ).dropna()
            daily["volume"] = 0
            df = daily
    if df.empty:
        raise ValueError(
            f"No sampled history for {ticker} yet. Search the symbol first and let samples collect."
        )
    assessment = risk_engine.assess(df, ticker)
    return assessment.to_dict()


def assess_portfolio_risk(user_id: int) -> Dict:
    positions = get_positions(user_id)
    assessments = []
    for p in positions:
        try:
            assessments.append(assess_ticker_risk(p["ticker"]))
        except ValueError:
            continue
    return risk_engine.assess_portfolio(assessments)
