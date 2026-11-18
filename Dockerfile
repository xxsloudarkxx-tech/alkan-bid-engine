FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIDKIT_ROOT=/app \
    BIDKIT_DELIVERY_DIR=/app/data/ENTREGAS/AGENTE \
    ANTHROPIC_BASE_URL=https://apikey.vnaipro.app/v1 \
    BIDKIT_API_BASE=https://apikey.vnaipro.app/v1 \
    BIDKIT_CLAUDE_MODEL=claude-sonnet-5 \
    PORT=8000

COPY pyproject.toml ./
COPY src ./src
COPY profiles ./profiles
COPY examples ./examples

RUN mkdir -p /app/data/ENTREGAS/AGENTE /app/data/security /app/data/uploads && pip install --no-cache-dir -e ".[api]"

EXPOSE 8000
CMD ["sh", "-c", "uvicorn bidkit.mobile_api:app --host 0.0.0.0 --port ${PORT:-8000}"]
