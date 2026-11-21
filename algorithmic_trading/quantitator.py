"""Quantitator's hourly summary, computed from the saved collection evidence."""
from collections import Counter

NAME = "Quantitator"


def briefing(evidence):
    quotes = evidence.get("quotes", [])
    news = evidence.get("news", [])
    observed = [q for q in quotes if q["status"] == "observed"]
    lines = [f"Quotes available for {len(observed)} of {len(quotes)} requested symbols."]
    for quote in observed:
        change = quote.get("change_percent")
        comparison = f"{change:+.2f}% versus previous close" if change is not None else "change unavailable"
        timestamp = quote.get("market_timestamp") or "unknown"
        lines.append(f"[{quote['id']}] {quote['ticker']}: {comparison}. Market time: {timestamp}.")
    topics = Counter(item["classification"]["topic"] for item in news if item.get("classification", {}).get("topic"))
    lines.append(f"Classified {sum(topics.values())} of {len(news)} saved headlines.")
    lines.extend(f"{topic}: {count}" for topic, count in topics.most_common())
    for feed in evidence.get("feeds", []):
        if feed["status"] != "ok":
            lines.append(f"{feed['source']}: unavailable during collection.")
    return "\n".join(lines)
