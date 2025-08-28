from datetime import datetime, date
from typing import List, Dict
import pandas as pd
from flask import current_app
from .models import db, Trade, HistoricalPrice
from .alpha_vantage_api import get_historical_data

def upsert_prices(ticker: str, df: pd.DataFrame) -> int:
    inserted = 0
    for d, row in df.iterrows():
        hp = HistoricalPrice.query.filter_by(ticker=ticker, date=d.date()).one_or_none()
        if hp is None:
            hp = HistoricalPrice(
                ticker=ticker,
                date=d.date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"] if not pd.isna(row["volume"]) else 0),
            )
            db.session.add(hp)
            inserted += 1
        else:
            hp.open = float(row["open"])
            hp.high = float(row["high"])
            hp.low = float(row["low"])
            hp.close = float(row["close"])
            hp.volume = int(row["volume"] if not pd.isna(row["volume"]) else 0)
    db.session.commit()
    return inserted

def fetch_and_store_prices(ticker: str, interval="daily", output_size="compact") -> int:
    api_key = current_app.config.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY not configured")
    df = get_historical_data(ticker, api_key, interval=interval, output_size=output_size)
    return upsert_prices(ticker, df)

def submit_trade(user_id: int, ticker: str, side: str, quantity: int, price: float = None, when: datetime | None = None) -> Dict:
    side = side.upper()
    assert side in ("BUY", "SELL"), "side must be BUY or SELL"
    when = when or datetime.utcnow()

    if price is None:
        latest = HistoricalPrice.query.filter_by(ticker=ticker).order_by(HistoricalPrice.date.desc()).first()
        if latest is None:
            raise RuntimeError("No price data for this ticker; fetch prices first")
        price = latest.close

    t = Trade(user_id=user_id, ticker=ticker, side=side, quantity=quantity, price=float(price), timestamp=when)
    db.session.add(t)
    db.session.commit()
    return {"trade_id": t.id, "ticker": t.ticker, "side": t.side, "quantity": t.quantity, "price": t.price}

def build_equity_curve(user_id: int, start: date | None = None) -> pd.DataFrame:
    trades = Trade.query.filter_by(user_id=user_id).order_by(Trade.timestamp.asc()).all()
    if not trades:
        return pd.DataFrame(columns=["date","equity"])

    symbols = sorted(list({t.ticker for t in trades}))

    price_frames = []
    for sym in symbols:
        rows = HistoricalPrice.query.filter_by(ticker=sym).order_by(HistoricalPrice.date.asc()).all()
        if not rows:
            continue
        df = pd.DataFrame([{"date": r.date, sym: r.close} for r in rows]).set_index("date")
        price_frames.append(df)
    if not price_frames:
        return pd.DataFrame(columns=["date","equity"])

    prices = pd.concat(price_frames, axis=1).sort_index().ffill()
    if start:
        prices = prices[prices.index >= pd.to_datetime(start).date()]

    positions = {sym: pd.Series(0, index=prices.index, dtype=float) for sym in symbols}

    for t in trades:
        d = pd.to_datetime(t.timestamp.date())
        if d not in prices.index:
            try:
                d = prices.index[prices.index.get_loc(d, method="backfill")]
            except Exception:
                continue
        q = t.quantity if t.side == "BUY" else -t.quantity
        positions[t.ticker].loc[d:] = positions[t.ticker].loc[d:] + q

    equity = None
    for sym in symbols:
        series_equity = positions[sym] * prices[sym]
        equity = series_equity if equity is None else (equity + series_equity)

    curve = pd.DataFrame({"date": equity.index, "equity": equity.values})
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

def get_positions(user_id: int, as_of: date | None = None) -> List[Dict]:
    """
    Aggregate positions (quantity and average cost) per ticker as of a date.
    Average cost = weighted average of BUY trades up to the date; SELL reduces quantity
    but does not change historical average cost calculation (FIFO not implemented here).
    """
    # Filter trades up to the date (inclusive)
    q = Trade.query.filter_by(user_id=user_id)
    if as_of:
        end_dt = datetime.combine(as_of, datetime.max.time())
        q = q.filter(Trade.timestamp <= end_dt)
    q = q.order_by(Trade.timestamp.asc())
    trades = q.all()

    if not trades:
        return []

    # Per-ticker aggregations
    pos_qty = {}
    buy_cost = {}
    buy_qty = {}

    for t in trades:
        sym = t.ticker
        if sym not in pos_qty:
            pos_qty[sym] = 0
            buy_cost[sym] = 0.0
            buy_qty[sym] = 0

        if t.side == "BUY":
            pos_qty[sym] += t.quantity
            buy_cost[sym] += t.price * t.quantity
            buy_qty[sym] += t.quantity
        else:  # SELL
            pos_qty[sym] -= t.quantity
            # For simplicity, do not adjust historical buy_cost/buy_qty on sells (not FIFO);
            # average cost is computed from total buys only.
            # If you want FIFO/realized PnL, we can add that later.

    # Get latest price as of date for valuation
    positions = []
    for sym in sorted(pos_qty.keys()):
        qty = pos_qty[sym]
        if qty == 0:
            continue

        # Latest close on/before date
        price_q = HistoricalPrice.query.filter_by(ticker=sym)
        if as_of:
            price_q = price_q.filter(HistoricalPrice.date <= as_of)
        hp = price_q.order_by(HistoricalPrice.date.desc()).first()
        last_close = float(hp.close) if hp else 0.0

        avg_cost = (buy_cost[sym] / buy_qty[sym]) if buy_qty[sym] > 0 else 0.0
        market_value = qty * last_close
        unrealized_pl = (last_close - avg_cost) * qty

        positions.append({
            "ticker": sym,
            "quantity": int(qty),
            "avg_cost": round(avg_cost, 4),
            "last_price": round(last_close, 4),
            "market_value": round(market_value, 2),
            "unrealized_pl": round(unrealized_pl, 2),
        })

    return positions