
import os
from flask import Flask, send_from_directory
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///trading.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ALPHA_VANTAGE_API_KEY"] = os.getenv("ALPHA_VANTAGE_API_KEY", "")

    from .models import db as _db
    _db.init_app(app)

    from .routes import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    with app.app_context():
        _db.create_all()

    return app
