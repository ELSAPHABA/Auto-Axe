# Phase 0 disposable development stack

Use only a dedicated fixture instance. Not a deployment or production auth.
Create the ignored environment file with `python scripts/init_dev_env.py`, then
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml config --quiet`.
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml up --build -d`.
Visit http://127.0.0.1:18174 (override with AUTOAXE_DEV_WEB_PORT if needed). PostgreSQL is private, API is private, executor has no network and is opt-in smoke only.
`docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile executor-smoke run --rm executor`.
The migration service uses the disposable admin secret; generated per-role passwords are ephemeral and not persisted, and no runtime API DB credential is needed yet. Phase 1 must introduce explicitly scoped runtime secret provisioning.
To stop this stack: `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml down`. Use `down -v` only to discard this explicitly disposable project volume. Do not run the fixture bootstrap on a production cluster.
