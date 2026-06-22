# Quantify — Paper Trading Simulator

A local Flask app that simulates stock trading with virtual money. Finnhub
quotes are sampled into the local SQLite database, creating private price
history over time without relying on a paid candle-history endpoint. A local,
rule-based risk advisor operates on the history available in the database.

## Setup

1. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and add your Finnhub key:
   ```
   cp .env.example .env
   ```

3. Export the variables (or use `python-dotenv` / your shell's `.env` support)
   and run:
   ```
   python run.py
   ```

The app runs at `http://127.0.0.1:5001`. Port 5000 is commonly occupied by
macOS AirPlay Receiver; change `APP_PORT` in `.env` if needed.

## Security note

Never put a real API key in a tracked file. Keep it in `.env`, which is
already ignored by Git.

## API overview

| Method | Path | Description |
|---|---|---|
| POST | `/api/users` | Create a user + virtual cash account (default $100,000) |
| GET | `/api/account/<user_id>` | Cash balance, positions, total equity |
| GET/POST | `/api/quote/<ticker>` | Read or refresh a Finnhub quote and store a local sample |
| GET | `/api/symbols?q=` | Search market symbols |
| GET | `/api/chart/<ticker>?range=24h` | Read locally sampled 24h/1w/1m/1y/all chart data |
| POST | `/api/trades` | Execute a simulated BUY/SELL against virtual cash |
| GET | `/api/trades?user_id=` | Trade history |
| GET | `/api/positions?user_id=` | Current holdings with live valuation |
| GET | `/api/performance?user_id=` | Equity curve + gain/loss summary |
| GET | `/api/risk/<ticker>` | Local risk/volatility/signal assessment for one ticker |
| GET | `/api/risk/portfolio?user_id=` | Risk rollup across a user's whole portfolio |

## How the risk advisor works

`risk_engine.py` is pure Python/pandas math over cached price history — no
external API calls, no black box:

- **Volatility**: standard deviation of daily returns, annualized
- **Average true range**: mean daily high-low range as % of close
- **Momentum**: 5-day vs 20-day moving average gap
- **Drawdown**: worst peak-to-trough decline in the lookback window
- **Risk level** (Low/Medium/High) and a BUY/HOLD/SELL **signal**, each with
  a plain-English `reasoning` list explaining exactly which numbers drove it

This is a heuristic for the simulation, not investment advice.

## Local history behavior

- Searching or refreshing a ticker stores a quote immediately.
- While `python run.py` remains active, watched tickers are sampled every
  30 seconds by default. Change `QUOTE_SAMPLE_INTERVAL_SECONDS` in `.env`.
- The open market view checks the local database every 30 seconds and redraws
  automatically. It does not make a duplicate Finnhub request.
- Keep `python run.py` running. Closing the terminal/server pauses collection;
  starting it again resumes all previously watched tickers automatically.
- Each cycle samples at most 25 tickers by default. Larger watchlists rotate
  fairly across cycles; adjust `QUOTE_SAMPLE_MAX_PER_CYCLE` cautiously.
- `24H` shows raw samples, `1W` uses 6-hour buckets, `1M` uses 12-hour
  buckets, and `1Y`/`ALL` use monthly buckets.
- `1M`, `1Y`, and `ALL` overlay close/high/low. Longer views initially show
  only the history collected since you began watching that ticker; no fake
  backfilled data is generated.
