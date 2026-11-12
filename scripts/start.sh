#!/bin/sh
set -e
alembic upgrade head
python scripts/seed.py
exec uvicorn critisizer.main:app --host 0.0.0.0 --port "${PORT:-8000}"