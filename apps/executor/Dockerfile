FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.10
COPY apps/executor/pyproject.toml apps/executor/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/executor/src ./src
RUN uv sync --locked --no-dev && useradd --uid 10002 --no-create-home executor
USER 10002
CMD ["/app/.venv/bin/python", "-m", "autoaxe_executor"]
