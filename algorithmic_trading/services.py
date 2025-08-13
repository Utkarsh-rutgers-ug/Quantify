from models import db, Trade, HistoricalData
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
import numpy as np

def simulate_trade(ticker, trade_type, price, quantity):
    new_trade = Trade(ticker=ticker, trade_type=trade_type, price=price, quantity=quantity)
    db.session.add(new_trade)
    db.session.commit()
    return {"status": "success", "trade_id": new_trade.id}

def get_historical_data(ticker, time_duration):
    # Mock data: Replace this with actual API/database calls
    historical_prices = [100, 102, 101, 105, 110, 108, 100, 90, 70, 71, 75, 74, 75, 76, 74, 78, 83, 90, 100, 130, 150, 155, 160, 161, 167]  # Example price data
    return historical_prices[-time_duration:]

def save_historical_data(ticker, data):
    for index, row in data.iterrows():
        historical_data = HistoricalData(ticker=ticker, date=index.date(), open=row["open"], high=row["high"], low=row["low"], close=row["close"], volume=row["volume"])
        db.session.add(historical_data)
    db.session.commit()


def calculate_var(historical_prices, confidence_level=0.95):
    returns = np.diff(historical_prices) / historical_prices[:-1]
    var = np.percentile(returns, (1 - confidence_level) * 100)
    return var

def calculate_sharpe_ratio(historical_prices, risk_free_rate=0.01):
    returns = np.diff(historical_prices) / historical_prices[:-1]
    mean_return = np.mean(returns)
    std_dev = np.std(returns)
    sharpe_ratio = (mean_return - risk_free_rate) / std_dev
    return sharpe_ratio


def riskCalculator(ticker, trade_type, price, quantity, current_time_stamp, time_duration, current_price):
    # Fetch historical data
    historical_prices = get_historical_data(ticker, time_duration)

    # Calculate Value at Risk (VaR)
    var = float(calculate_var(historical_prices))  # Cast to native Python float

    # Calculate Sharpe Ratio
    sharpe_ratio = float(calculate_sharpe_ratio(historical_prices))  # Cast to native Python float

    # Calculate potential loss
    potential_loss = quantity * (current_price - price)

    # Return risk metrics
    return {
        "ticker": ticker,
        "trade_type": trade_type,
        "price": price,
        "quantity": quantity,
        "var": var,
        "sharpe_ratio": sharpe_ratio,
        "potential_loss": potential_loss
    }

