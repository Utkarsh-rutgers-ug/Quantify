from flask import Blueprint, request, jsonify, Flask
from models import db, Trade, Strategy
from data_manager import save_historical_data
import pandas as pd
from alpha_vantage_api import get_historical_data
from services import HistoricalData


routes = Blueprint('routes', __name__)
app = Flask(__name__)

@app.route('/fetch_and_save/<ticker>', methods=['GET'])
def fetch_and_save_data(ticker):
    """
    API endpoint to fetch and save historical stock data for a given ticker.
    """
    data = get_historical_data(ticker, interval="daily", output_size="compact")
    if isinstance(data, pd.DataFrame):
        save_historical_data(ticker, data)
        return jsonify({"message": f"Historical data for {ticker} saved successfully!"})
    else:
        return jsonify({"error": data.get("error", "Unknown error")}), 400


def init_routes(app):
    app.register_blueprint(routes)

@routes.route('/submit_trade', methods=['POST'])
def submit_trade():
    data = request.get_json()
    new_trade = Trade(ticker=data['ticker'], trade_type=data['trade_type'], price=data['price'], quantity=data['quantity'], timestamp=data['timestamp'])
    db.session.add(new_trade)
    db.session.commit()
    return jsonify({"message": "Trade submitted successfully!"})

@routes.route('/get_trades', methods=['GET'])
def get_trades():
    trades = Trade.query.all()
    return jsonify([{"id": trade.id,
        "ticker": trade.ticker,
        "trade_type": trade.trade_type,
        "price": trade.price,
        "quantity": trade.quantity,
        "timestamp": trade.timestamp
    } for trade in trades])
