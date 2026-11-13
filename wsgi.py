"""WSGI entry point.

    Dev:   flask --app wsgi run --debug
    Prod:  gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 wsgi:app

Use ONE worker process: the listing store lives in process memory, so with
several workers a write handled by one would be invisible to the others.
The store is thread-safe, so scale with --threads instead.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
