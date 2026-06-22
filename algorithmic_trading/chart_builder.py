"""Turn locally stored quote snapshots into chart-ready time buckets."""
from datetime import datetime, timedelta
from typing import Iterable


RANGE_CONFIG = {
    "24h": {"lookback": timedelta(hours=24), "bucket": None, "multi_line": False},
    "1w": {"lookback": timedelta(days=7), "bucket": timedelta(hours=6), "multi_line": False},
    "1m": {"lookback": timedelta(days=30), "bucket": timedelta(hours=12), "multi_line": True},
    "1y": {"lookback": timedelta(days=365), "bucket": "month", "multi_line": True},
    "all": {"lookback": None, "bucket": "month", "multi_line": True},
}


def _value(sample, name):
    return getattr(sample, name) if hasattr(sample, name) else sample[name]


def _floor_time(timestamp: datetime, bucket):
    if bucket == "month":
        return datetime(timestamp.year, timestamp.month, 1)
    seconds = int(bucket.total_seconds())
    epoch_start = datetime(1970, 1, 1)
    epoch = int((timestamp - epoch_start).total_seconds())
    return epoch_start + timedelta(seconds=epoch - (epoch % seconds))


def build_chart(samples: Iterable, range_name: str, now: datetime | None = None) -> dict:
    if range_name not in RANGE_CONFIG:
        raise ValueError("range must be one of: 24h, 1w, 1m, 1y, all")

    config = RANGE_CONFIG[range_name]
    now = now or datetime.utcnow()
    cutoff = now - config["lookback"] if config["lookback"] else None
    rows = sorted(
        [s for s in samples if cutoff is None or _value(s, "timestamp") >= cutoff],
        key=lambda s: _value(s, "timestamp"),
    )

    if not rows:
        return {"range": range_name, "multi_line": config["multi_line"], "points": []}

    if config["bucket"] is None:
        points = [
            {
                "timestamp": _value(s, "timestamp").isoformat() + "Z",
                "close": float(_value(s, "price")),
                "high": float(_value(s, "high") or _value(s, "price")),
                "low": float(_value(s, "low") or _value(s, "price")),
            }
            for s in rows
        ]
    else:
        buckets = {}
        for sample in rows:
            key = _floor_time(_value(sample, "timestamp"), config["bucket"])
            buckets.setdefault(key, []).append(sample)
        points = []
        for key, bucket_rows in sorted(buckets.items()):
            prices = [float(_value(s, "price")) for s in bucket_rows]
            highs = [float(_value(s, "high") or _value(s, "price")) for s in bucket_rows]
            lows = [float(_value(s, "low") or _value(s, "price")) for s in bucket_rows]
            points.append(
                {
                    "timestamp": key.isoformat() + "Z",
                    "close": prices[-1],
                    "high": max(max(prices), max(highs)),
                    "low": min(min(prices), min(lows)),
                }
            )

    return {"range": range_name, "multi_line": config["multi_line"], "points": points}
