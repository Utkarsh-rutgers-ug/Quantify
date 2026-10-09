"""Small, explicit client for the Finnhub quote and symbol-search endpoints."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math
import requests

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubError(RuntimeError):
    pass


@dataclass
class FinnhubQuote:
    ticker: str
    price: float
    open: float
    high: float
    low: float
    previous_close: float
    change: float
    change_percent: float
    provider_timestamp: int
    fetched_at: datetime

    def to_dict(self):
        data = asdict(self)
        data["fetched_at"] = self.fetched_at.isoformat() + "Z"
        return data


def _get(path: str, token: str, **params):
    if not token:
        raise FinnhubError("FINNHUB_API_KEY is not configured. Add it to your .env file.")
    params["token"] = token
    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        raise FinnhubError("Finnhub request timed out. Try again later.") from None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        message = {
            401: "Finnhub authentication failed. Check your local API key.",
            403: "Finnhub access denied. Check your key and plan.",
            429: "Finnhub rate limit reached. Try again later.",
        }.get(status, "Finnhub service request failed. Try again later.")
        raise FinnhubError(message) from None
    except requests.RequestException:
        # Request exceptions can include the full URL, including the API token.
        raise FinnhubError("Finnhub connection failed. Try again later.") from None
    except ValueError:
        raise FinnhubError("Finnhub returned an invalid response.") from None
    if isinstance(data, dict) and data.get("error"):
        raise FinnhubError("Finnhub rejected the request. Check your key, plan, and symbol.")
    if not isinstance(data, dict):
        raise FinnhubError("Finnhub returned an invalid response.")
    return data


def get_quote(ticker: str, token: str) -> FinnhubQuote:
    ticker = ticker.strip().upper()
    data = _get("/quote", token, symbol=ticker)
    try:
        numbers = {key: float(data.get(key) or 0) for key in ("c", "o", "h", "l", "pc", "d", "dp", "t")}
        if not all(math.isfinite(value) for value in numbers.values()):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise FinnhubError("Finnhub returned invalid quote values.") from None
    price = numbers["c"]
    if price <= 0:
        raise FinnhubError(
            f"No quote is available for {ticker}. Check the symbol and your Finnhub plan/key."
        )
    return FinnhubQuote(
        ticker=ticker,
        price=price,
        open=numbers["o"] or price,
        high=numbers["h"] or price,
        low=numbers["l"] or price,
        previous_close=numbers["pc"] or price,
        change=numbers["d"],
        change_percent=numbers["dp"],
        provider_timestamp=int(numbers["t"]),
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


def search_symbols(query: str, token: str, limit: int = 10) -> list:
    data = _get("/search", token, q=query.strip())
    results = data.get("result", []) if isinstance(data, dict) else []
    return [
        {
            "symbol": item.get("symbol", ""),
            "description": item.get("description", ""),
            "type": item.get("type", ""),
            "display_symbol": item.get("displaySymbol", item.get("symbol", "")),
        }
        for item in results[:limit]
        if item.get("symbol")
    ]
