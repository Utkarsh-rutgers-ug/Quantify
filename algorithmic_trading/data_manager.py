from alpha_vantage_api import get_historical_data  # Import your API function
from models import db, HistoricalData

def save_historical_data(ticker, data):
    """
    Save historical stock data to the database.

    :param ticker: The stock ticker symbol.
    :param data: A pandas DataFrame containing the historical data.
    """
    try:
        for index, row in data.iterrows():
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
    except Exception as e:
        print(f"Error saving data for {ticker}: {e}")
