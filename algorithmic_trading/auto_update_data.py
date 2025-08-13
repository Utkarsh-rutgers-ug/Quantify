from apscheduler.schedulers.background import BackgroundScheduler
from alpha_vantage_api import get_historical_data
from models import db, HistoricalData  # Update paths if necessary


def update_historical_data(tickers):
    """
    Fetch and save historical stock data for a list of tickers.
    :param tickers: List of stock ticker symbols (e.g., ['AAPL', 'GOOGL']).
    """
    for ticker in tickers:
        try:
            # Fetch historical data
            data = get_historical_data(ticker, interval="daily", output_size="compact")
            if data is None or data.empty:
                print(f"No data returned for {ticker}. Skipping.")
                continue

            # Save data to the database
            for index, row in data.iterrows():
                # Avoid duplicates by checking if the record exists
                existing_record = HistoricalData.query.filter_by(ticker=ticker, date=index.date()).first()
                if existing_record:
                    continue

                historical_record = HistoricalData(
                    ticker=ticker,
                    date=index.date(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"]
                )
                db.session.add(historical_record)
            db.session.commit()
            print(f"Updated historical data for {ticker}.")
        except Exception as e:
            print(f"Error updating data for {ticker}: {e}")


def schedule_updates(tickers, interval_hours=24):
    """
    Schedule periodic updates of historical stock data.
    :param tickers: List of stock ticker symbols.
    :param interval_hours: Time interval in hours between updates.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=lambda: update_historical_data(tickers),
                      trigger="interval",
                      hours=interval_hours)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")

    # Keep the script running
    try:
        while True:
            pass
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")


if __name__ == "__main__":
    # Example tickers to update
    tickers_to_update = ["AAPL", "GOOGL", "MSFT"]
    schedule_updates(tickers_to_update)
