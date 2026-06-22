"""
routes.py
REST API for the paper-trading simulation.
"""
from flask import Blueprint, request
from datetime import datetime

from models import db, User, Account, Trade, Position
from finnhub_api import FinnhubError
import services

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


# --- Users / accounts -------------------------------------------------

@api_bp.route("/users", methods=["GET"])
def list_users():
    rows = User.query.order_by(User.id.asc()).all()
    return {"users": [{"id": u.id, "name": u.name, "email": u.email} for u in rows]}


@api_bp.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(force=True)
    starting_balance = float(data.get("starting_balance", services.STARTING_BALANCE))
    try:
        user = services.create_user_with_account(
            name=data["name"], email=data["email"], starting_balance=starting_balance
        )
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    return {"id": user.id, "name": user.name, "email": user.email}


@api_bp.route("/account/<int:user_id>", methods=["GET"])
def account_summary(user_id):
    try:
        summary = services.get_portfolio_summary(user_id)
    except ValueError as e:
        return {"error": str(e)}, 404
    return summary


# --- Market data --------------------------------------------------------

@api_bp.route("/quote/<ticker>", methods=["GET", "POST"])
def quote(ticker):
    ticker = ticker.upper()
    try:
        if request.method == "POST" or request.args.get("refresh") == "1":
            result = services.fetch_and_store_quote(ticker)
        else:
            result = services.latest_quote(ticker) or services.fetch_and_store_quote(ticker)
    except FinnhubError as e:
        return {"error": str(e)}, 502
    return result


@api_bp.route("/symbols", methods=["GET"])
def symbols():
    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return {"results": []}
    try:
        return {"results": services.search_market_symbols(query)}
    except FinnhubError as e:
        return {"error": str(e)}, 502


@api_bp.route("/chart/<ticker>", methods=["GET"])
def chart(ticker):
    range_name = request.args.get("range", "24h").lower()
    try:
        return services.get_quote_chart(ticker.upper(), range_name)
    except ValueError as e:
        return {"error": str(e)}, 400

@api_bp.route("/prices/<ticker>", methods=["POST"])
def ingest_prices(ticker):
    output_size = request.args.get("output_size", "compact")
    try:
        inserted = services.fetch_and_store_prices(ticker.upper(), output_size=output_size)
    except Exception as e:
        return {"error": str(e)}, 502
    return {"ticker": ticker.upper(), "rows_upserted": inserted}


@api_bp.route("/prices/<ticker>", methods=["GET"])
def get_prices(ticker):
    df = services.get_price_history(ticker.upper())
    return {
        "ticker": ticker.upper(),
        "prices": [
            {
                "date": str(idx.date()),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": int(row["volume"]),
            }
            for idx, row in df.iterrows()
        ],
    }


# --- Trading (paper / simulated, virtual cash only) ---------------------

@api_bp.route("/trades", methods=["POST"])
def create_trade():
    data = request.get_json(force=True)
    try:
        res = services.submit_trade(
            user_id=int(data["user_id"]),
            ticker=data["ticker"].upper(),
            side=data["side"],
            quantity=int(data["quantity"]),
            price=float(data["price"]) if data.get("price") is not None else None,
        )
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}, 400
    return res


@api_bp.route("/trades", methods=["GET"])
def list_trades():
    user_id = request.args.get("user_id", type=int)
    q = Trade.query
    if user_id:
        q = q.filter_by(user_id=user_id)
    rows = q.order_by(Trade.timestamp.asc()).all()
    return {
        "trades": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "ticker": t.ticker,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "realized_pnl": t.realized_pnl,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in rows
        ]
    }


@api_bp.route("/positions", methods=["GET"])
def positions():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return {"error": "user_id is required"}, 400
    return {"positions": services.get_positions(user_id)}


@api_bp.route("/performance", methods=["GET"])
def get_performance():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return {"error": "user_id is required"}, 400
    start = request.args.get("start")
    start_at = datetime.fromisoformat(start) if start else None
    try:
        curve = services.build_equity_curve(user_id, start=start_at)
    except ValueError as e:
        return {"error": str(e)}, 404
    summary = services.performance_summary(curve)
    return {
        "curve": [
            {"timestamp": d.isoformat() + "Z", "equity": round(float(v), 2)}
            for d, v in zip(curve["timestamp"], curve["equity"])
        ],
        "summary": summary,
    }


# --- Risk advisor (local, rule-based, no external AI calls) -------------

@api_bp.route("/risk/<ticker>", methods=["GET"])
def risk_for_ticker(ticker):
    try:
        assessment = services.assess_ticker_risk(ticker.upper())
    except ValueError as e:
        return {"error": str(e)}, 404
    return assessment


@api_bp.route("/risk/portfolio", methods=["GET"])
def risk_for_portfolio():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return {"error": "user_id is required"}, 400
    return services.assess_portfolio_risk(user_id)
