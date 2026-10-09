"""
routes.py
REST API for the paper-trading simulation.
"""
from flask import Blueprint, request, current_app
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone

from models import db, User, Trade
from finnhub_api import FinnhubError
import services

api_bp = Blueprint("api", __name__)


@api_bp.route("/news/sources", methods=["GET"])
def news_sources():
    from news import SOURCES
    return {"sources": [{"id": key, "name": value["name"], "feed_url": value["url"]}
                        for key, value in SOURCES.items()]}


@api_bp.route("/news", methods=["GET"])
def news_articles():
    from news import SOURCES, serialize_article
    from models import NewsArticle
    try:
        limit = int(request.args.get("limit", "50"))
        before_id = int(request.args["before_id"]) if "before_id" in request.args else None
    except ValueError:
        return {"error": "limit and before_id must be integers"}, 400
    if not 1 <= limit <= 100 or (before_id is not None and before_id <= 0):
        return {"error": "limit must be 1–100 and before_id must be positive"}, 400
    query = NewsArticle.query
    source = request.args.get("source")
    if source:
        if source not in SOURCES:
            return {"error": "Unknown news source"}, 400
        query = query.filter_by(source_id=source)
    ticker = request.args.get("ticker")
    if ticker:
        if ticker.upper() != "MRK":
            return {"error": "The initial company filter supports MRK only"}, 400
        # Include ambiguous Merck mentions, clearly labelled for human review.
        query = query.filter(NewsArticle.mrk_match.isnot(None))
    person = request.args.get("person")
    if person:
        if person != "jim-cramer":
            return {"error": "The initial person filter supports jim-cramer only"}, 400
        query = query.filter_by(cramer_mention=True)
    if before_id:
        query = query.filter(NewsArticle.id < before_id)
    rows = query.order_by(NewsArticle.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {"articles": [serialize_article(row) for row in page],
            "next_before_id": page[-1].id if len(rows) > limit else None,
            "order": "newest collected first", "coverage": "feed headlines and summaries only"}


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
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not {"name", "email"} <= data.keys():
        return {"error": "Expected a JSON object with name and email"}, 400
    starting_balance = data.get("starting_balance", services.STARTING_BALANCE)
    try:
        user = services.create_user_with_account(
            name=data["name"], email=data["email"], starting_balance=starting_balance
        )
    except ValueError as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    except SQLAlchemyError:
        db.session.rollback()
        return {"error": "Could not create trader. Use a unique email and try again."}, 400
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
    except Exception:
        db.session.rollback()
        return {"error": "Historical price update failed. Check provider configuration and limits."}, 502
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
    data = request.get_json(silent=True)
    required = {"user_id", "ticker", "side", "quantity"}
    if not isinstance(data, dict) or not required <= data.keys():
        return {"error": "Expected a JSON object with user_id, ticker, side, and quantity"}, 400
    if "price" in data:
        return {"error": "Execution price is determined by the server; omit price"}, 400
    if data.keys() - required:
        return {"error": "Unsupported trade fields"}, 400
    try:
        res = services.submit_trade(
            user_id=data["user_id"],
            ticker=data["ticker"],
            side=data["side"],
            quantity=data["quantity"],
        )
    except FinnhubError as e:
        db.session.rollback()
        return {"error": str(e)}, 502
    except ValueError as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Trade could not be saved due to a database error")
        return {"error": "Trade could not be saved. Please try again later."}, 503
    return res


@api_bp.route("/trades", methods=["GET"])
def list_trades():
    user_id = request.args.get("user_id", type=int)
    if user_id is None or user_id <= 0:
        return {"error": "A positive user_id is required"}, 400
    q = Trade.query.filter_by(user_id=user_id)
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
                "timestamp": t.timestamp.isoformat() + "Z",
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
    try:
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        if start_at is not None and start_at.tzinfo is not None:
            start_at = start_at.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return {"error": "start must be an ISO timestamp"}, 400
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
