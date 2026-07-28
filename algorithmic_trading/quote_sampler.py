"""Background collection of Finnhub quotes for every watched symbol."""
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

_next_ticker_index = 0


def sample_watched_tickers(app):
    import services

    global _next_ticker_index
    with app.app_context():
        tickers = services.list_watched_tickers()
        if not tickers:
            return

        # Bound each cycle and rotate fairly through larger watchlists.
        max_per_cycle = max(1, int(os.getenv("QUOTE_SAMPLE_MAX_PER_CYCLE", "25")))
        count = min(len(tickers), max_per_cycle)
        selected = [
            tickers[(_next_ticker_index + offset) % len(tickers)]
            for offset in range(count)
        ]
        _next_ticker_index = (_next_ticker_index + count) % len(tickers)

        for ticker in selected:
            try:
                services.fetch_and_store_quote(ticker)
            except Exception as exc:
                app.logger.warning("Could not sample %s: %s", ticker, exc)


def _build_scheduler(app, scheduler_class):
    """Configure a scheduler without deciding how its process stays alive."""
    interval_seconds = max(30, int(os.getenv("QUOTE_SAMPLE_INTERVAL_SECONDS", "30")))
    scheduler = scheduler_class(timezone="UTC")
    scheduler.add_job(
        sample_watched_tickers,
        "interval",
        seconds=interval_seconds,
        args=[app],
        id="finnhub_quote_sampler",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler, interval_seconds


def _log_sampler_started(app, interval_seconds):
    app.logger.info(
        "Automatic Finnhub sampler started: every %s seconds", interval_seconds
    )


def start_quote_sampler(app):
    """Start sampling in the background while another local process stays alive."""
    scheduler, interval_seconds = _build_scheduler(app, BackgroundScheduler)
    scheduler.start()
    # Collect once immediately instead of waiting for the first interval.
    sample_watched_tickers(app)
    _log_sampler_started(app, interval_seconds)
    return scheduler


def run_quote_sampler_worker(app):
    """Run the sampler as the foreground process for a dedicated worker."""
    scheduler, interval_seconds = _build_scheduler(app, BlockingScheduler)
    # Collect once immediately before the scheduler begins its blocking loop.
    sample_watched_tickers(app)
    _log_sampler_started(app, interval_seconds)
    scheduler.start()
