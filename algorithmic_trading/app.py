"""
app.py
Single Flask app factory. (Previously this logic was duplicated between
app.py and __init__.py with two different import styles -- consolidated
here as the one source of truth.)
"""
import os
from flask import Flask, send_from_directory
from dotenv import load_dotenv
from models import db
from routes import api_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))  # reads the app's .env no matter where Python starts


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///trading.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ALPHA_VANTAGE_API_KEY"] = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    app.config["FINNHUB_API_KEY"] = os.getenv("FINNHUB_API_KEY", "")

    db.init_app(app)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return send_from_directory(static_dir, "index.html")
        return {"status": "Algorithmic trading simulator API is running. See /api/health."}

    with app.app_context():
        db.create_all()

    return app


app = create_app()
