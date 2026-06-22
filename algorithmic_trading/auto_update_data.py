"""
auto_update_data.py
Optional background scheduler that periodically refreshes cached price
history for a list of tickers. Run this as a separate process if you want
prices to stay fresh without manually calling POST /api/prices/<ticker>.
"""
from apscheduler.schedulers.background import BackgroundScheduler
import services
from app import app


def update_historical_data(tickers):
    with app.app_context():
        for ticker in tickers:
            try:
                inserted = services.fetch_and_store_prices(ticker, output_size="compact")
                print(f"Updated {ticker}: {inserted} new rows.")
            except Exception as e:
                print(f"Error updating data for {ticker}: {e}")


def schedule_updates(tickers, interval_hours=24):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: update_historical_data(tickers),
        trigger="interval",
        hours=interval_hours,
    )
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            pass
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")


if __name__ == "__main__":
    tickers_to_update = ["AAPL", "GOOGL", "MSFT"]
    schedule_updates(tickers_to_update)
