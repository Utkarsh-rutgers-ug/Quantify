"""
alpha_vantage_api.py
Thin wrapper around the Alpha Vantage REST API for historical OHLCV data.
"""
import requests
import pandas as pd

BASE_URL = "https://www.alphavantage.co/query"

_FUNCTION_MAP = {
    "daily": "TIME_SERIES_DAILY_ADJUSTED",
    "weekly": "TIME_SERIES_WEEKLY_ADJUSTED",
    "monthly": "TIME_SERIES_MONTHLY_ADJUSTED",
}

_TS_KEY_MAP = {
    "TIME_SERIES_DAILY_ADJUSTED": "Time Series (Daily)",
    "TIME_SERIES_WEEKLY_ADJUSTED": "Weekly Adjusted Time Series",
    "TIME_SERIES_MONTHLY_ADJUSTED": "Monthly Adjusted Time Series",
}


class AlphaVantageError(RuntimeError):
    """Raised when Alpha Vantage returns an error, a rate-limit note, or unusable data."""


def get_historical_data(
    ticker: str,
    api_key: str,
    interval: str = "daily",
    output_size: str = "compact",
) -> pd.DataFrame:
    """
    Fetch historical OHLCV data for a ticker.

    :param ticker: stock symbol, e.g. "AAPL"
    :param api_key: Alpha Vantage API key
    :param interval: "daily" | "weekly" | "monthly"
    :param output_size: "compact" (latest ~100 points) or "full"
    :return: DataFrame indexed by date with columns open, high, low, close, volume
    """
    if not api_key:
        raise AlphaVantageError("No Alpha Vantage API key configured.")

    function = _FUNCTION_MAP.get(interval, "TIME_SERIES_DAILY_ADJUSTED")

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

    ts_key = _TS_KEY_MAP[function]
    if ts_key not in data:
        # Common cases: bad symbol, rate limit ("Note"), or invalid key ("Information")
        message = data.get("Note") or data.get("Information") or data.get("Error Message") or data
        raise AlphaVantageError(f"Alpha Vantage error for {ticker}: {message}")

    df = pd.DataFrame.from_dict(data[ts_key], orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.rename(
        columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "6. volume": "volume",
        }
    )
    cols = ["open", "high", "low", "close", "volume"]
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[cols].sort_index()
