# ── Prism API ── Dev Dockerfile ──────────────────────────────────
FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Source code is volume-mounted at runtime for hot-reload,
# but we copy it here as a fallback for non-compose usage.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
