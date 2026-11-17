# ---- stage 1: build the React app -------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: FastAPI serves the API and the built UI ------------------------------
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LLM_MODE=cached
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend backend
COPY samples samples
COPY --from=frontend /fe/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8000
# Render/Railway inject $PORT. A single worker is intentional: runs execute in background threads and the
# SSE stream reads progress from the database, so scaling out is possible but not needed for a demo.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
