from flask import Flask
from sqlalchemy.exc import SQLAlchemyError
from models import db, HistoricalData
from routes import init_routes
from userinfo import User

def create_app():
    app = Flask(__name__)

    # Configure your DB (example using SQLite; adapt as needed)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///mydatabase.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    init_routes(app)

    @app.route("/")
    def home():
        return "Hello, this is our single-DB app."

    # Initialize all tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
