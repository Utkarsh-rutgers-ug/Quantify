from app import app

# For gunicorn (AWS EB): "web: gunicorn wsgi:app"
# No need to run app.run() here.