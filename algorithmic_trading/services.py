
from datetime import datetime, date
from typing import Dict
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
                volume=int(row["volume"] or 0),
            )
            db.session.add(hp)
            inserted += 1
        else:
            hp.open = float(row["open"]); hp.high = float(row["high"]); hp.low = float(row["low"])
            hp.close = float(row["close"]); hp.volume = int(row["volume"] or 0)
    db.session.commit()
    return inserted

def fetch_and_store_prices(ticker: str, interval="daily", output_size="compact") -> int:
    api_key = current_app.config.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY not configured")
    df = get_historical_data(ticker, api_key, interval=interval, output_size=output_size)
    return upsert_prices(ticker, df)

def submit_trade(user_id: int, ticker: str, side: str, quantity: int, price: float | None = None, when: datetime | None = None) -> Dict:
    side = side.upper()
    assert side in ("BUY", "SELL")
    when = when or datetime.utcnow()

    if price is None:
        latest = HistoricalPrice.query.filter_by(ticker=ticker).order_by(HistoricalPrice.date.desc()).first()
        if not latest:
            raise RuntimeError("No price data for ticker; fetch prices first")
        price = latest.close

    t = Trade(user_id=user_id, ticker=ticker, side=side, quantity=quantity, price=float(price), timestamp=when)
    db.session.add(t); db.session.commit()
    return {"trade_id": t.id, "ticker": t.ticker, "side": t.side, "quantity": t.quantity, "price": t.price}

def build_equity_curve(user_id: int, start: date | None = None) -> pd.DataFrame:
    trades = Trade.query.filter_by(user_id=user_id).order_by(Trade.timestamp.asc()).all()
    if not trades: return pd.DataFrame(columns=["date","equity"])

    symbols = sorted({t.ticker for t in trades})
    price_frames = []
    for sym in symbols:
        rows = HistoricalPrice.query.filter_by(ticker=sym).order_by(HistoricalPrice.date.asc()).all()
        if not rows: continue
        df = pd.DataFrame([{"date": r.date, sym: r.close} for r in rows]).set_index("date")
        price_frames.append(df)
    if not price_frames: return pd.DataFrame(columns=["date","equity"])

    prices = pd.concat(price_frames, axis=1).sort_index().ffill()
    if start: prices = prices[prices.index >= pd.to_datetime(start).date()]

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
        equity = series_equity if equity is None else equity + series_equity

    return pd.DataFrame({"date": equity.index, "equity": equity.values})

def performance_summary(curve: pd.DataFrame) -> Dict:
    if curve.empty:
        return {"equity_start":0,"equity_end":0,"gain_abs":0,"gain_pct":0}
    s = float(curve["equity"].iloc[0]); e = float(curve["equity"].iloc[-1])
    gain = e - s; pct = (gain / s * 100.0) if s else 0.0
    return {"equity_start":round(s,2),"equity_end":round(e,2),"gain_abs":round(gain,2),"gain_pct":round(pct,2)}
