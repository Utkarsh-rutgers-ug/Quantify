"""Small, explicit client for the Finnhub quote and symbol-search endpoints."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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
    except requests.RequestException as exc:
        raise FinnhubError(f"Finnhub request failed: {exc}") from exc
    except ValueError as exc:
        raise FinnhubError("Finnhub returned an invalid response.") from exc
    if isinstance(data, dict) and data.get("error"):
        raise FinnhubError(f"Finnhub error: {data['error']}")
    return data


def get_quote(ticker: str, token: str) -> FinnhubQuote:
    ticker = ticker.strip().upper()
    data = _get("/quote", token, symbol=ticker)
    price = float(data.get("c") or 0)
    if price <= 0:
        raise FinnhubError(
            f"No quote is available for {ticker}. Check the symbol and your Finnhub plan/key."
        )
    return FinnhubQuote(
        ticker=ticker,
        price=price,
        open=float(data.get("o") or price),
        high=float(data.get("h") or price),
        low=float(data.get("l") or price),
        previous_close=float(data.get("pc") or price),
        change=float(data.get("d") or 0),
        change_percent=float(data.get("dp") or 0),
        provider_timestamp=int(data.get("t") or 0),
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
