web: gunicorn app:app --log-file -
worker: celery -A celery_worker.celery worker --beat --loglevel=info --concurrency=2
voice: python -m agents.voice_bot_agent.server
