from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class HistoricalData(db.Model):
    __tablename__ = "historical_data"
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(10), primary_key=False)
    date = db.Column(db.Date, primary_key=False)
    open = db.Column(db.Float, primary_key=False)
    high = db.Column(db.Float, primary_key=False)
    low = db.Column(db.Float, primary_key=False)
    close = db.Column(db.Float, primary_key=False)
    volume = db.Column(db.Integer, primary_key=False)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(10), nullable=False)
    trade_type = db.Column(db.String(4), nullable=False)  # Buy or Sell
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)

class Strategy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    parameters = db.Column(db.JSON, nullable=False)  # Store strategy parameters as JSON

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    portfolio_value = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
