#!/bin/bash
set -e

# This script is used as the start command on Render
echo "Starting deployment process..."

# Check if migrations need to be initialized (stamped)
# We check if the alembic_version table exists to decide if we need to stamp or upgrade
echo "Verifying database migration status..."
# Automatically stamp the database if it exists but has no history
python3 alembic_helper.py

echo "Applying migrations..."
alembic upgrade head

echo "Starting application server..."
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
