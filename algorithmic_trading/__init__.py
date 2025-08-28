# algorithmic_trading/__init__.py
import os
from flask import Flask, send_from_directory
from .models import db
from .routes import api_bp

def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///trading.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ALPHA_VANTAGE_API_KEY"] = os.getenv("ALPHA_VANTAGE_API_KEY", "")

    db.init_app(app)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), "index.html")

    with app.app_context():
        db.create_all()
    return app
