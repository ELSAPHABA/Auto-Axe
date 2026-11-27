FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS scraper-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.10
COPY apps/scraper/pyproject.toml apps/scraper/uv.lock ./
RUN uv sync --locked --no-install-project
COPY apps/scraper/src ./src
COPY apps/scraper/tests ./tests
RUN uv sync --locked && useradd --uid 10003 --no-create-home scraper

# Separate optional image. The ordinary scraper image never installs Chromium.
FROM scraper-base AS seibro-browser
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright HOME=/tmp
RUN uv sync --locked --group browser \
    && /app/.venv/bin/python -m playwright install --with-deps chromium
USER 10003
ENTRYPOINT ["/app/.venv/bin/python", "-m", "autoaxe_scraper.seibro_browser", "--reserved-capture"]

FROM scraper-base AS scraper
USER 10003
CMD ["/app/.venv/bin/python", "-m", "pytest", "-p", "no:cacheprovider", "tests", "-q"]
