# Quantify

Quantify is a local paper-trading application for studying how financial news
relates to market behavior. It combines a simulated account, stored market data,
a locally trained news classifier, and a local language model for briefings and
portfolio questions.

The application uses Flask, SQLite, pandas, and plain JavaScript. It does not
connect to a broker or place real orders.

## Current functionality

- Paper accounts with cash balances, positions, trade history, and equity curves.
- Finnhub quote collection and charts built from locally stored observations.
- A rule-based risk assessment using daily price history.
- BBC and CNBC feed collection with publication times, retrieval times, and source links.
- Hourly briefings saved in the database, with explicit source failures and data timestamps.
- A financial-news topic classifier trained locally from labeled examples.
- Qwen chat through Ollama, with read-only access to the selected paper account.
- Event studies comparing news timestamps with stock and benchmark price observations.

## The two models

The news classifier in `news_model.py` is a multinomial naive Bayes model over
words and adjacent word pairs. It assigns financial-news topics such as earnings,
regulation, monetary policy, and company news. Collection is handled by explicit
feed and quote clients; the classifier does not browse the web.

Qwen3 8B runs locally through Ollama. It explains the collected evidence, writes
briefings, and answers questions about the selected trader's cash, positions,
and recent trades. It does not collect sources, train the classifier, or execute
orders.

The classifier reached 76.22% topic accuracy on 3,352 validation examples after
normalized duplicate removal, against a 21.93% majority-class baseline. Some
rare topics performed poorly. These are classification results, not stock-return
or trading results. See the [evaluation record](algorithmic_trading/docs/news-model-evaluation.json)
and [training instructions](algorithmic_trading/README.md#train-the-news-classifier).

A model that predicts market response to news has not been trained yet. The
current event-study code provides measurements for that work.

## Run locally

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp algorithmic_trading/.env.example algorithmic_trading/.env
```

Set `FINNHUB_API_KEY` in `algorithmic_trading/.env`, then start the application:

```bash
.venv/bin/python run.py
```

Open [localhost:5001](http://127.0.0.1:5001/). On Windows, use
`.venv\Scripts\python.exe` in place of `.venv/bin/python`.

For local chat and generated briefings, install [Ollama](https://ollama.com/) and
run:

```bash
ollama pull qwen3:8b
ollama serve
```

If the Ollama desktop application already provides the local service, a second
`ollama serve` process is unnecessary. Without Ollama, Quantify can still collect
and save evidence, but it cannot generate chat replies or briefing interpretations.

Model weights and datasets are not included in the repository. Train the news
classifier using the instructions below; until then, collected news is marked
as unclassified. The ordinary trading and collection features remain available.

## Collection and persistence

`run.py` starts the web application and background collection. Watched symbols
are sampled every 30 seconds by default. The news briefing runs on startup and
then hourly, with at most one collection per UTC hour.

For collection without the web server:

```bash
.venv/bin/python algorithmic_trading/worker.py
```

Closing a browser does not stop collection. Stopping the worker, shutting down
the computer, or letting it sleep pauses collection. Restarting resumes new
collection; missed periods are not reconstructed automatically.

Quotes, accounts, trades, news, and briefings are stored in the local database.
The last 24 briefings are selectable in the interface; older records remain
stored. Chat history is kept in browser memory and clears on reload or a trader
change.

## Limitations

This is a local research application. The trader selector is not authentication,
and the existing deployment entrypoints do not make it suitable for unrestricted
public access.

News coverage is limited to the configured feeds. A recently retrieved quote
may still have an old market timestamp. Charts represent collected observations,
not complete exchange history. The risk advisor needs at least 21 daily
observations and uses fixed rules.

AI interpretations can be wrong. The application exposes the evidence and its
timestamps so those interpretations can be checked. News/price associations do
not establish causation or demonstrate a profitable strategy.

## Planned work

Deployment work includes authentication, database migrations, PostgreSQL
validation, market-hours handling, stale-price checks, and worker health reporting.
Hosted collection will use a separate worker process from the web application.

Research work includes measuring news-related price responses, evaluating
forecasts without look-ahead bias, and expanding source coverage to company and
government statements. Portfolio concentration, diversification, and source
reliability analysis remain planned. Rule-based risk assessments will stay
separate from experimental forecasts.

## Development

[Application documentation](algorithmic_trading/README.md) covers the code layout,
configuration, model training, event-study commands, and tests.

Credentials, databases, trained weights, training data, and personal development
notes are excluded from version control. Keep real keys in the ignored `.env`
file. Code licensing is described in [LICENSE](LICENSE); datasets and model
weights have their own terms.
