FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Copy application code
COPY . .

# Apply schema migrations, seed reference data, embed the catalog (all
# idempotent; embedding is best effort), then serve
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && (python -m app.embed_catalog || true) && uvicorn app.main:app --host 0.0.0.0 --port 7200"]

EXPOSE 7200
