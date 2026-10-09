# Application development

This directory contains the Flask application, collection worker, models, and
browser interface. Commands below assume a virtual environment was created at
the repository root as described in the [main README](../README.md).

## Code layout

| File | Responsibility |
|---|---|
| `app.py` | Application factory, configuration, route registration, and table creation |
| `models.py` | Paper accounts, trades, positions, price history, and news records |
| `services.py` | Trading operations, valuations, historical data, and performance replay |
| `routes.py` | Trading, market-data, news, and risk API endpoints |
| `finnhub_api.py`, `alpha_vantage_api.py` | Provider clients |
| `quote_sampler.py` | Quote sampling and hourly briefing scheduling |
| `news.py` | RSS/Atom parsing, source validation, and deduplication |
| `news_model.py` | Local news-topic model training and inference |
| `market_assistant.py` | Stored briefings, local Qwen requests, and portfolio context |
| `event_study.py` | Timestamped price imports and news-response measurements |
| `risk_engine.py` | Price-based risk heuristics |
| `chart_builder.py` | Chart time buckets |
| `static/index.html` | Dashboard layout and trading interface |
| `static/assistant.js` | Briefing selection and chat interface |
| `run.py`, `worker.py`, `wsgi.py` | Local application, collection-only, and web-only entrypoints |

## Configuration

Copy `.env.example` to `.env` in this directory. The application reads it on
startup.

| Variable | Default or purpose |
|---|---|
| `FINNHUB_API_KEY` | Required for quote retrieval and symbol search |
| `ALPHA_VANTAGE_API_KEY` | Optional historical importer; availability depends on provider access |
| `DATABASE_URL` | Defaults to `sqlite:///trading.db` in Flask's instance directory |
| `APP_PORT` | `5001` |
| `QUOTE_SAMPLE_INTERVAL_SECONDS` | `30`, with a minimum of 30 |
| `QUOTE_SAMPLE_MAX_PER_CYCLE` | `25`; larger watchlists rotate between cycles |
| `QUANTIFY_CHAT_MODEL` | `qwen3:8b`; must be installed in local Ollama |

The hourly briefing includes up to 12 recently collected headlines and quotes
for up to 25 watched symbols. This is bounded coverage, not a comprehensive news
search. Qwen runs at `127.0.0.1:11434`, with an 8,192-token context and bounded
output. The news classifier runs separately without Ollama.

`wsgi.py` and the root `Procfile` run only the web application. A hosted setup
also needs a collection worker, access to its model service, persistent storage,
and user authentication. Do not run multiple collection processes unnecessarily.

## Train the news classifier

Download the publisher's training and validation CSV files from
[Twitter Financial News Topic](https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic).
Review the dataset card and preserve its license information. The publisher
lists MIT; underlying content rights should be reviewed before redistribution.

From the repository root, place the files in an ignored local directory:

```bash
mkdir -p algorithmic_trading/local_data/news-topics
curl -fL https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic/resolve/main/topic_train.csv -o algorithmic_trading/local_data/news-topics/topic_train.csv
curl -fL https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic/resolve/main/topic_valid.csv -o algorithmic_trading/local_data/news-topics/topic_valid.csv
curl -fL https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic/raw/main/README.md -o algorithmic_trading/local_data/news-topics/DATASET_CARD.md
.venv/bin/python algorithmic_trading/news_model.py algorithmic_trading/local_data/news-topics/topic_train.csv algorithmic_trading/local_data/news-topics/topic_valid.csv
```

Training writes `instance/news_topic_model.json` and
`instance/news_topic_model.metrics.json` beside the application. Both are ignored
by Git. The saved evaluation record includes hashes of the dataset files used
for the reported run; upstream files may change.

The trainer removes normalized duplicates and conflicting training labels,
limits the vocabulary to 20,000 features, and learns weights for 20 topics.
Inputs with insufficient known vocabulary are left unclassified. Scores are not
calibrated probabilities. The validation split is not chronological, near-duplicate
stories may remain, and performance on current BBC/CNBC headlines is unmeasured.

## News and event studies

From the application directory, collect a feed snapshot or this hour's briefing:

```bash
cd algorithmic_trading
../.venv/bin/python -m flask --app app news-fetch
../.venv/bin/python -m flask --app app briefing-refresh
```

The briefing command skips an already claimed UTC hour. Collection failures and
unavailable Ollama are recorded instead of being presented as a complete report.

Find an article ID through `/api/news`, then link it to a reviewed company and
event category. Replace `123` with an existing article ID:

```bash
../.venv/bin/python -m flask --app app event-link 123 MRK --category guidance
../.venv/bin/python -m flask --app app event-prices-import /path/to/prices.csv --source provider-name
../.venv/bin/python -m flask --app app event-report --ticker MRK --category guidance --source provider-name --benchmark SPY
```

Price files use `ticker,timestamp,price` columns. Timestamps must include a timezone.
Include both the stock and benchmark. Use actual observation times or minute-bar
end times, not download times. Use a consistent price-adjustment convention.
Imports are limited to 100,000 rows and reject conflicting observations atomically.

The report measures returns at 1, 5, 15, and 60 elapsed minutes, subtracts benchmark
returns, and finds the first observed move beyond a configurable threshold
(default 1 percentage point). Baseline and endpoint prices must be recent enough;
gaps invalidate response-time estimates. Closed sessions are not interpreted as
slow reactions. Daily and multi-session response measurements are not implemented.

Monthly summaries include coverage, response rates, and median response time among
responders. These are descriptive research measurements, not causal findings or
trading signals. Later observations are outcome labels and must not become
prediction-time features.

## Assistant and account context

The chat API takes the selected `user_id`, a message, and up to six history
messages. It reads that paper account's cash, up to 20 open positions, and 20
recent trades. Missing prices remain unavailable rather than becoming zero.
Private account records are supplied only to the local model for that response;
they are not written into shared briefings or used to train the news classifier.

The selected database username is used for chat. Shared briefings do not have a
personal greeting. The model has no tools for placing orders. Trader selection
is not authentication.

## Main endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/users` | Create a paper account |
| GET | `/api/account/<user_id>` | Cash, positions, and cached valuation |
| GET/POST | `/api/quote/<ticker>` | Read or refresh a quote |
| GET | `/api/chart/<ticker>?range=24h` | Stored price chart |
| POST | `/api/trades` | Place a paper order at a server-held price |
| GET | `/api/trades?user_id=1` | Selected account's trade history |
| GET | `/api/performance?user_id=1` | Account equity curve |
| GET | `/api/risk/<ticker>` | Rule-based risk assessment |
| GET | `/api/news` | Collected headlines and provenance |
| GET | `/api/events/<event_id>/response?source=provider-name` | Event response measurements |
| GET | `/api/assistant/briefings` | Latest 24 saved briefings |
| POST | `/api/assistant/chat` | Local model response using account and market evidence |

## Tests

From this directory, with the virtual environment at the repository root:

```bash
DATABASE_URL=sqlite:///:memory: ../.venv/bin/python -m unittest discover -p 'test_*.py'
DATABASE_URL=sqlite:///:memory: ../.venv/bin/python test_quote_history.py
DATABASE_URL=sqlite:///:memory: ../.venv/bin/python test_simulation.py
```

The tests use isolated databases and mocked providers. They cover account and
trade validation, quote history, feed parsing, event timing, import rollback,
assistant account scoping, scheduler entrypoints, and maintenance regressions.
The two script-based smoke tests are run separately because unittest discovery
does not execute their `main()` functions.
