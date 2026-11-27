FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.10
COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/backend/src ./src
COPY apps/backend/alembic.ini ./
COPY apps/backend/migrations ./migrations
RUN uv sync --locked --no-dev && useradd --uid 10001 --no-create-home autoaxe
USER 10001
FROM backend AS pizzint-collector
COPY apps/scraper/src/autoaxe_scraper/__init__.py apps/scraper/src/autoaxe_scraper/policy.py apps/scraper/src/autoaxe_scraper/transport.py /opt/pizzint/autoaxe_scraper/
ENV PYTHONPATH=/opt/pizzint
CMD ["/app/.venv/bin/python", "-m", "autoaxe.entrypoints.pizzint_cli"]

FROM backend AS api
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "autoaxe.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000"]
