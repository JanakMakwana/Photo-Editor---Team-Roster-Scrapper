# syntax=docker/dockerfile:1
# --------------------------------------------------------------------------
# Multi-stage Production Dockerfile for VeloRoster Pro
# Supports Render Docker, Railway, Fly.io, or VPS container deployment
# --------------------------------------------------------------------------

FROM python:3.11-slim

# Install system dependencies for OpenCV, Pillow, MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/ ./backend/
COPY saas_db.py saas_auth.py saas_email.py studio.py process_portraits.py ./

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=False \
    REMBG_MODEL=u2netp \
    PORT=8000

# Collect static assets
RUN python backend/manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/healthz || exit 1

# Run migrations, seed base tiers, and start Gunicorn WSGI server
CMD ["sh", "-c", "python backend/manage.py migrate && python backend/manage.py seed_demo_data && gunicorn --chdir backend veloroster.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]

