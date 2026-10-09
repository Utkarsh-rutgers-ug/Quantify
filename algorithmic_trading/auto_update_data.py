"""
auto_update_data.py
Optional background scheduler that periodically refreshes cached price
history for a list of tickers. Run this as a separate process if you want
prices to stay fresh without manually calling POST /api/prices/<ticker>.
"""
from apscheduler.schedulers.blocking import BlockingScheduler
import services
from app import app


def update_historical_data(tickers):
    with app.app_context():
        for ticker in tickers:
            try:
                inserted = services.fetch_and_store_prices(ticker, output_size="compact")
                print(f"Updated {ticker}: {inserted} new rows.")
            except Exception:
                services.db.session.rollback()
                app.logger.warning("Historical update failed for %s", ticker)


def schedule_updates(tickers, interval_hours=24):
    scheduler = BlockingScheduler()
    scheduler.add_job(
        func=update_historical_data,
        args=[tickers],
        trigger="interval",
        hours=interval_hours,
    )
    print("Scheduler started. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        if scheduler.running:
            scheduler.shutdown()
        print("Scheduler stopped.")


if __name__ == "__main__":
    tickers_to_update = ["AAPL", "GOOGL", "MSFT"]
    schedule_updates(tickers_to_update)
