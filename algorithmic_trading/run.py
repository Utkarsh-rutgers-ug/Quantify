import os

from app import app
from quote_sampler import start_quote_sampler

if __name__ == "__main__":
    # Disable Flask's reloader so it cannot start two background samplers.
    start_quote_sampler(app)
    port = int(os.getenv("APP_PORT", "5001"))
    app.run(debug=True, use_reloader=False, port=port)
