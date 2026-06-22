import os
import sys

APP_DIR = os.path.join(os.path.dirname(__file__), "algorithmic_trading")
sys.path.insert(0, APP_DIR)

from app import app

# For gunicorn (AWS EB): "web: gunicorn wsgi:app"
# No need to run app.run() here.
