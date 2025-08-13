from datetime import datetime

# Import the riskCalculator function from your services.py
from services import riskCalculator

# Test the function with example data
if __name__ == "__main__":
    result = riskCalculator(
        ticker="AAPL",
        trade_type="Buy",
        price=169,
        quantity=30,
        current_time_stamp=datetime.now(),
        time_duration=25,
        current_price=170
    )
    print("Risk Calculation Result:", result)
