# syntax=docker/dockerfile:1
# --------------------------------------------------------------------------
# Multi-stage Dockerfile for VeloRoster AI (FastAPI + React SaaS)
# Optimized for Railway, Fly.io, Koyeb, Render Docker, and Self-Hosted VPS
# Deploy time: ~60-90s with cached layers
# --------------------------------------------------------------------------

# --- Stage 1: Build Modern React Frontend ---
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit

COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python Application Runner ---
FROM python:3.11-slim AS runner

# Install essential system libraries for OpenCV, Pillow, and MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for maximum layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source and database engine
COPY backend/ ./backend/
COPY saas_db.py saas_auth.py saas_email.py studio.py process_portraits.py ./

# Copy built frontend assets from Stage 1 into frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Default environment configuration
ENV PORT=8000 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    REMBG_MODEL=u2netp

# Expose server port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/healthz || exit 1

# Start the FastAPI ASGI server with auto-port detection
CMD ["python", "-m", "backend.main"]
