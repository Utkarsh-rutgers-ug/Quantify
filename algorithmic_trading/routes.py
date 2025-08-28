from flask import Blueprint, request
from datetime import datetime, date
from .models import db, User, Trade, HistoricalPrice
from .services import (
    fetch_and_store_prices,
    submit_trade,
    build_equity_curve,
    performance_summary,
    get_positions,
)
api_bp = Blueprint("api", __name__)

@api_bp.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}

@api_bp.route("/prices/<ticker>", methods=["POST"])
def ingest_prices(ticker):
    output_size = request.args.get("output_size", "compact")
    inserted = fetch_and_store_prices(ticker.upper(), output_size=output_size)
    return {"ticker": ticker.upper(), "rows_upserted": inserted}

@api_bp.route("/prices/<ticker>", methods=["GET"])
def get_prices(ticker):
    rows = (HistoricalPrice.query
        .filter_by(ticker=ticker.upper())
        .order_by(HistoricalPrice.date.asc())
        .all())
    return {"ticker": ticker.upper(), "prices": [
        {"date": r.date.isoformat(), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
        for r in rows
    ]}

@api_bp.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(force=True)
    u = User(name=data["name"], email=data["email"])
    db.session.add(u)
    db.session.commit()
    return {"id": u.id, "name": u.name, "email": u.email}

@api_bp.route("/trades", methods=["POST"])
def create_trade():
    data = request.get_json(force=True)
    res = submit_trade(
        user_id=int(data["user_id"]),
        ticker=data["ticker"].upper(),
        side=data["side"],
        quantity=int(data["quantity"]),
        price=float(data["price"]) if "price" in data and data["price"] is not None else None,
    )
    return res

@api_bp.route("/trades", methods=["GET"])
def list_trades():
    user_id = request.args.get("user_id", type=int)
    q = Trade.query
    if user_id:
        q = q.filter_by(user_id=user_id)
    rows = q.order_by(Trade.timestamp.asc()).all()
    return {"trades": [{
        "id": t.id, "user_id": t.user_id, "ticker": t.ticker, "side": t.side,
        "quantity": t.quantity, "price": t.price, "timestamp": t.timestamp.isoformat()
    } for t in rows]}

@api_bp.route("/performance", methods=["GET"])
def get_performance():
    user_id = request.args.get("user_id", type=int)
    start = request.args.get("start")
    start_date = datetime.fromisoformat(start).date() if start else None
    curve = build_equity_curve(user_id, start=start_date)
    summary = performance_summary(curve)
    return {
        "curve": [{"date": d.strftime("%Y-%m-%d"), "equity": float(v)} for d, v in zip(curve["date"], curve["equity"])],
        "summary": summary,
    }

@api_bp.route("/positions", methods=["GET"])
def positions():
    user_id = request.args.get("user_id", type=int)
    as_of_raw = request.args.get("date")
    as_of = None
    if as_of_raw:
        try:
            as_of = datetime.fromisoformat(as_of_raw).date()
        except Exception:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400
    pos = get_positions(user_id, as_of=as_of)
    return {"positions": pos, "as_of": as_of.isoformat() if as_of else None}