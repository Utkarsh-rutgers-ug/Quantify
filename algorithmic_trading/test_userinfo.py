from userinfo import db, save_user, add_stock_to_portfolio, get_user_info
from app import app

with app.app_context():  # Activate the Flask app context
    # Add a new user
    user = save_user(name="John Doe", email="john.doe@example.com")
    print(f"User Created: {user.name}, ID: {user.id}")

    # Add stocks to the portfolio
    stock1 = add_stock_to_portfolio(
        user_id=user.id,
        ticker="AAPL",
        quantity=10,
        purchase_price=150,
        current_price=155
    )
    stock2 = add_stock_to_portfolio(
        user_id=user.id,
        ticker="GOOGL",
        quantity=5,
        purchase_price=2800,
        current_price=2900
    )

    print(f"Stocks Added: {stock1.ticker}, {stock2.ticker}")

    # Get user information
    user_info = get_user_info(user.id)
    print("User Info:", user_info)
