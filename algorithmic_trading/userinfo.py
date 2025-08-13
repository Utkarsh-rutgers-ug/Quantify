from flask_sqlalchemy import SQLAlchemy
from models import db

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)  # Unique ID for each user
    name = db.Column(db.String(50), nullable=False)  # User's name
    email = db.Column(db.String(100), unique=True, nullable=False)  # Email address
    portfolio_value = db.Column(db.Float, default=0.0)  # Total portfolio value
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())  # Timestamp for when the user was added

class PortfolioItem(db.Model):
    __tablename__ = 'portfolio_items'
    id = db.Column(db.Integer, primary_key=True)  # Unique ID for each portfolio item
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Link to the User table
    ticker = db.Column(db.String(10), nullable=False)  # Stock ticker
    quantity = db.Column(db.Integer, nullable=False)  # Quantity of stocks owned
    purchase_price = db.Column(db.Float, nullable=False)  # Purchase price per stock
    current_price = db.Column(db.Float, nullable=False)  # Current price per stock

def save_user(name, email):
    user = User(name=name, email=email)
    db.session.add(user)
    db.session.commit()
    return user

def save_portfolio_item(user_id, ticker, quantity, purchase_price, current_price):
    portfolio_item = PortfolioItem(user_id=user_id, ticker=ticker, quantity=quantity, purchase_price=purchase_price, current_price=current_price)
    db.session.add(portfolio_item)
    db.session.commit()
    return portfolio_item

def add_stock_to_portfolio(user_id, ticker, quantity, purchase_price, current_price):
    portfolio_item = PortfolioItem(
        user_id=user_id,
        ticker=ticker,
        quantity=quantity,
        purchase_price=purchase_price,
        current_price=current_price
    )
    db.session.add(portfolio_item)
    db.session.commit()
    return portfolio_item

def get_user_info(user_id):
    user = User.query.filter_by(id=user_id).first()
    portfolio = PortfolioItem.query.filter_by(user_id=user_id).all()
    portfolio_summary = [
        {
            "ticker": item.ticker,
            "quantity": item.quantity,
            "purchase_price": item.purchase_price,
            "current_price": item.current_price
        } for item in portfolio
    ]
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "portfolio_value": user.portfolio_value,
        "portfolio": portfolio_summary
    }
