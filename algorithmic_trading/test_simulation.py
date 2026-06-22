"""
test_simulation.py
End-to-end smoke test for the paper-trading simulation, using synthetic
price data (no network/API key required) so it can run anywhere.

Run with: python test_simulation.py
d8s3d9hr01qlj6ffuks0d8s3d9hr01qlj6ffuksg
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app
from models import db
import services
import risk_engine


def make_synthetic_prices(days=40, start_price=100.0, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days, freq="D")
    returns = rng.normal(loc=0.001, scale=0.015, size=days)
    closes = start_price * np.cumprod(1 + returns)
    highs = closes * (1 + rng.uniform(0, 0.01, size=days))
    lows = closes * (1 - rng.uniform(0, 0.01, size=days))
    opens = closes * (1 + rng.normal(0, 0.005, size=days))
    volumes = rng.integers(1_000_000, 5_000_000, size=days)
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )
    return df


def main():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        # 1. Create user with default $100,000 virtual balance
        user = services.create_user_with_account(name="Test Trader", email="trader@example.com")
        print(f"Created user {user.id} ({user.name})")

        account = services.get_account(user.id)
        assert account.cash_balance == services.STARTING_BALANCE
        print(f"Starting cash balance: {account.cash_balance:.2f}")

        # 2. Seed synthetic price history (stand-in for Alpha Vantage data)
        df = make_synthetic_prices(days=40, start_price=150.0)
        rows = services.upsert_prices("AAPL", df)
        print(f"Inserted {rows} synthetic AAPL price rows")

        # 3. Run the risk engine on it
        assessment = services.assess_ticker_risk("AAPL")
        print("Risk assessment for AAPL:")
        for k, v in assessment.items():
            print(f"  {k}: {v}")

        # 4. Execute a BUY using the latest cached close
        last_price = services.latest_close("AAPL")
        qty = 50
        result = services.submit_trade(user_id=user.id, ticker="AAPL", side="BUY", quantity=qty)
        print("BUY result:", result)
        assert result["cash_balance"] < services.STARTING_BALANCE

        # 5. Confirm position was created
        positions = services.get_positions(user.id)
        assert len(positions) == 1 and positions[0]["ticker"] == "AAPL"
        print("Positions after BUY:", positions)

        # 6. Sell half, confirm realized P&L is computed and cash increases
        sell_result = services.submit_trade(user_id=user.id, ticker="AAPL", side="SELL", quantity=qty // 2)
        print("SELL result:", sell_result)
        assert sell_result["realized_pnl"] is not None

        # 7. Try to overspend -- should raise
        try:
            services.submit_trade(user_id=user.id, ticker="AAPL", side="BUY", quantity=1_000_000)
            print("FAIL: overspend did not raise")
            sys.exit(1)
        except ValueError as e:
            print(f"Correctly rejected overspend: {e}")

        # 8. Portfolio summary + portfolio-level risk rollup
        summary = services.get_portfolio_summary(user.id)
        print("Portfolio summary:", summary)

        portfolio_risk = services.assess_portfolio_risk(user.id)
        print("Portfolio risk rollup:", portfolio_risk)

        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
