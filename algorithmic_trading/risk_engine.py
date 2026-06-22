"""
risk_engine.py

A fully local, rule-based "risk advisor". No external AI calls, no API key
needed beyond the Alpha Vantage price history you already fetch.

It looks at price history for a ticker and produces:
  - volatility metrics (daily stdev annualized, ATR-like range)
  - momentum (short vs long moving average, recent return)
  - max drawdown over the lookback window
  - a risk_level: "Low" | "Medium" | "High"
  - a signal: "BUY" | "HOLD" | "SELL" with a plain-English reason

This is intentionally simple and transparent (no black box) so every
number it outputs can be traced back to a formula. It is NOT investment
advice -- it's a toy heuristic for the simulation.
"""
from dataclasses import dataclass, asdict
from typing import Optional
import math
import pandas as pd


@dataclass
class RiskAssessment:
    ticker: str
    as_of: str
    last_close: float
    daily_volatility_pct: float       # stdev of daily returns, in %
    annualized_volatility_pct: float  # daily_volatility * sqrt(252), in %
    avg_true_range_pct: float         # average daily high-low range as % of close
    momentum_5_20_pct: float          # (5-day MA / 20-day MA - 1) * 100
    return_20d_pct: float             # total return over the lookback window, in %
    max_drawdown_pct: float           # worst peak-to-trough drop in the window, in %
    risk_level: str                   # Low / Medium / High
    signal: str                       # BUY / HOLD / SELL
    reasoning: list

    def to_dict(self):
        return asdict(self)


def _annualized_vol(daily_returns: pd.Series) -> float:
    return float(daily_returns.std() * math.sqrt(252) * 100)


def _max_drawdown_pct(close: pd.Series) -> float:
    running_max = close.cummax()
    drawdown = (close - running_max) / running_max
    return float(drawdown.min() * 100)


def assess(df: pd.DataFrame, ticker: str, lookback_days: int = 20) -> RiskAssessment:
    """
    :param df: DataFrame with columns open, high, low, close, volume,
               indexed by date ascending (as returned by alpha_vantage_api).
    :param ticker: symbol, for labeling.
    :param lookback_days: window size for momentum / drawdown calculations.
    """
    if df is None or df.empty:
        raise ValueError(f"No price history available for {ticker}")

    df = df.sort_index()
    window = df.tail(max(lookback_days, 21))  # need >=21 rows for a 20d MA

    close = window["close"]
    daily_returns = close.pct_change().dropna()

    daily_vol_pct = float(daily_returns.std() * 100) if len(daily_returns) > 1 else 0.0
    ann_vol_pct = _annualized_vol(daily_returns) if len(daily_returns) > 1 else 0.0

    true_range_pct = ((window["high"] - window["low"]) / window["close"] * 100)
    atr_pct = float(true_range_pct.mean())

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else close.mean()
    momentum_pct = float((ma5 / ma20 - 1) * 100) if ma20 else 0.0

    return_pct = float((close.iloc[-1] / close.iloc[0] - 1) * 100)
    drawdown_pct = _max_drawdown_pct(close)
    last_close = float(close.iloc[-1])

    reasoning = []

    # --- Risk level: based on annualized volatility ---
    # Rough, transparent thresholds. Tune freely.
    if ann_vol_pct < 20:
        risk_level = "Low"
    elif ann_vol_pct < 40:
        risk_level = "Medium"
    else:
        risk_level = "High"
    reasoning.append(
        f"Annualized volatility is {ann_vol_pct:.1f}%, classified as {risk_level} risk."
    )

    if drawdown_pct < -15:
        reasoning.append(
            f"Max drawdown over the window was {drawdown_pct:.1f}%, a significant recent decline."
        )
        if risk_level == "Low":
            risk_level = "Medium"

    # --- Signal: simple momentum + drawdown rule ---
    # Not a recommendation -- just a transparent heuristic for the simulation.
    score = 0
    if momentum_pct > 1.5:
        score += 1
        reasoning.append(f"Short-term momentum is positive ({momentum_pct:.1f}% 5d/20d MA gap).")
    elif momentum_pct < -1.5:
        score -= 1
        reasoning.append(f"Short-term momentum is negative ({momentum_pct:.1f}% 5d/20d MA gap).")

    if return_pct > 5:
        score += 1
        reasoning.append(f"Price is up {return_pct:.1f}% over the lookback window.")
    elif return_pct < -5:
        score -= 1
        reasoning.append(f"Price is down {return_pct:.1f}% over the lookback window.")

    if drawdown_pct < -20:
        score -= 1
        reasoning.append("Drawdown exceeds 20%, a defensive flag against new buying.")

    if risk_level == "High" and score <= 0:
        signal = "SELL"
    elif score >= 2:
        signal = "BUY"
    elif score <= -1:
        signal = "SELL"
    else:
        signal = "HOLD"

    reasoning.append(f"Composite heuristic score: {score} -> {signal}.")

    return RiskAssessment(
        ticker=ticker,
        as_of=str(window.index[-1].date()),
        last_close=round(last_close, 4),
        daily_volatility_pct=round(daily_vol_pct, 3),
        annualized_volatility_pct=round(ann_vol_pct, 2),
        avg_true_range_pct=round(atr_pct, 3),
        momentum_5_20_pct=round(momentum_pct, 3),
        return_20d_pct=round(return_pct, 3),
        max_drawdown_pct=round(drawdown_pct, 3),
        risk_level=risk_level,
        signal=signal,
        reasoning=reasoning,
    )


def assess_portfolio(position_assessments: list) -> dict:
    """
    Roll several per-ticker RiskAssessment dicts into a portfolio-level view.
    :param position_assessments: list of dicts with at least 'risk_level', 'signal', 'ticker'
    """
    if not position_assessments:
        return {"overall_risk_level": "N/A", "flags": [], "positions": []}

    risk_rank = {"Low": 0, "Medium": 1, "High": 2}
    worst = max(position_assessments, key=lambda a: risk_rank.get(a["risk_level"], 0))

    flags = [
        f"{a['ticker']}: {a['signal']} ({a['risk_level']} risk)"
        for a in position_assessments
        if a["signal"] == "SELL" or a["risk_level"] == "High"
    ]

    return {
        "overall_risk_level": worst["risk_level"],
        "flags": flags,
        "positions": position_assessments,
    }
