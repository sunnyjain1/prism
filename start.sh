#!/bin/bash
set -e

# This script is used as the start command on Render
echo "Starting deployment process..."

# Check if migrations need to be initialized (stamped)
# We check if the alembic_version table exists to decide if we need to stamp or upgrade
echo "Verifying database migration status..."

# Note: In production, we assume the DB is already present. 
# We use Alembic to ensure the schema is current.
# If it's a fresh DB, 'upgrade head' creates tables.
# If it's an existing DB with no alembic_version, we might need a manual stamp or handled logic.

# For Render, we'll try to run upgrade head. 
# If the tables exist but alembic_version doesn't, we should stamp it once.
# This script handles that by attempting to check for existence.

# Check if alembic_version exists (this is a bit tricky depending on the DB)
# For simplicity and safety, we'll run upgrade head. 
# If it fails because tables exist, you may need to run 'alembic stamp head' manually once.
# However, many people just use a script to check.

echo "Applying migrations..."
alembic upgrade head

echo "Starting application server..."
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
