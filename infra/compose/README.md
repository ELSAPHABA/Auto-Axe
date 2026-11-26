# Phase 0–1 disposable development stack

Use only a dedicated fixture instance. Not a deployment or production auth.
Create the ignored environment file with `python scripts/init_dev_env.py`, then
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml config --quiet`.
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml up --build -d`.
Visit http://127.0.0.1:18174 (override with AUTOAXE_DEV_WEB_PORT if needed). PostgreSQL is private, API is private, executor has no network and is opt-in smoke only.
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile executor-smoke run --rm executor`.
Phase 1: rerun init_dev_env.py for existing installations to create missing fixture role passwords without replacing existing ones. The ignored environment file is local only. Migrate uses disposable admin credentials; API uses the market read role, fixture collector uses the separate write role. No market provider or broker credential is needed.

Run a synthetic collection job: `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile fixture-collect run --rm fixture-collector`. Read `http://127.0.0.1:18174/api/v1/market/observations?series_id=FIXTURE_PRICE`. This is not external data. See [Phase 1 implementation](../../docs/development/PHASE_01_IMPLEMENTATION.md).
Recurring synthetic smoke (bounded two cycles): `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile fixture-collect run --rm --build fixture-collector /app/.venv/bin/python -m autoaxe.entrypoints.market_cli fixture-poll --cycles 2 --sleep 5`. Rebuild the profile image after changing backend code. External collection remains disabled.
To stop this stack: `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml down`. Use `down -v` only to discard this explicitly disposable project volume. Do not run the fixture bootstrap on a production cluster.
