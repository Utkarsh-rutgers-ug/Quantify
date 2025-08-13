
import requests
import pandas as pd

BASE_URL = "https://www.alphavantage.co/query"

def get_historical_data(ticker: str, api_key: str, interval: str = "daily", output_size: str = "compact") -> pd.DataFrame:
    function_map = {
        "daily": "TIME_SERIES_DAILY_ADJUSTED",
        "weekly": "TIME_SERIES_WEEKLY_ADJUSTED",
        "monthly": "TIME_SERIES_MONTHLY_ADJUSTED",
    }
    function = function_map.get(interval, "TIME_SERIES_DAILY_ADJUSTED")

    params = {
        "function": function,
        "symbol": ticker,
        "apikey": api_key,
        "datatype": "json",
        "outputsize": output_size,
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    key_map = {
        "TIME_SERIES_DAILY_ADJUSTED": "Time Series (Daily)",
        "TIME_SERIES_WEEKLY_ADJUSTED": "Weekly Adjusted Time Series",
        "TIME_SERIES_MONTHLY_ADJUSTED": "Monthly Adjusted Time Series",
    }
    ts_key = key_map[function]
    if ts_key not in data:
        raise RuntimeError(f"AlphaVantage error: {data.get('Note') or data.get('Information') or data}")

    df = pd.DataFrame.from_dict(data[ts_key], orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={
        "1. open": "open",
        "2. high": "high",
        "3. low": "low",
        "4. close": "close",
        "6. volume": "volume",
    })
    cols = ["open", "high", "low", "close", "volume"]
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[cols].sort_index()
