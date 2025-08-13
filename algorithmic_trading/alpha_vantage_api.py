import requests
import pandas as pd

ALPHA_VANTAGE_API_KEY = "J7YLYUPJ2CQMFLHD"
BASE_URL = "https://www.alphavantage.co/query"

def get_historical_data(ticker, interval="daily", output_size="compact"):
    try:
        function_map = {"daily": "TIME_SERIES_DAILY", "weekly": "TIME_SERIES_WEEKLY", "monthly": "TIME_SERIES_MONTHLY"}
        function = function_map.get(interval, "TIME_SERIES_DAILY")

        params = {":function": function, ":symbol": ticker, "apikey": ALPHA_VANTAGE_API_KEY, "datatype": "json", "outputsize": output_size}
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()

        data = response.json()

        time_series_key = list(data.keys())[1]  # e.g., "Time Series (Daily)"
        time_series = data[time_series_key]

        df = pd.DataFrame.from_dict(time_series, orient="index")
        df = df.rename(columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. volume": "volume"
        })
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()  # Sort by date (ascending)
        return df
    except Exception as e:
        return {"error": str(e)}



