from app import app

# For gunicorn (e.g. AWS EB): "web: gunicorn wsgi:app"
# No need to call app.run() here.
