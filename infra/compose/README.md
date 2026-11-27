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

## PizzINT DOUGHCON collector

Private single-user deployment; the separate `pizzint.yaml` never bootstraps a
database, exposes a port, or enables trading. It contains only the fixed
DOUGHCON HTTPS API adapter and the market ledger runtime client (not a browser
worker). Do not run any other PizzINT polling process against the same service.

1. Use the existing PostgreSQL 17 `autoaxe_market` database with the
   market runtime/read roles, migrated to `0006_pizzint_cadence` using the
   normal migration owner procedure. Ensure the canonical PizzINT catalog row
   is present (`seed_catalog` for admin-only catalog provisioning, not fixture
   cluster bootstrap). Verify the current [terms](https://www.pizzint.watch/terms):
   public API reasonable rate limiting; informational/educational use only.
   No specific 5-minute rate is guaranteed by the provider.
2. On a trusted admin host only, record the source approval through the
   existing administrator-only `set_permission` function. Set
   `AUTOAXE_MARKET_ADMIN_DSN` in that host's environment (not in the worker).
   Example, after reviewing the terms and confirming the private deployment:

   ```sh
   uv run --project apps/backend --locked python -c "import os, psycopg; from autoaxe.infrastructure.market_store import set_permission; c=psycopg.connect(os.environ['AUTOAXE_MARKET_ADMIN_DSN']); set_permission(c,'pizzint',approved=True,evidence='PizzINT terms 2026-06-25, private informational DOUGHCON public API; operator reviewed terms',fetch=True,storage=True); c.commit(); c.close()"
   ```

   Keep redistribution and trading disabled. For revocation use the same
   administrative function with approved=False, fetch=False, storage=False
   and an appropriate evidence note; no deletion of history is required.
3. Supply `AUTOAXE_MARKET_RUNTIME_DSN` (the existing market runtime login,
   not admin) and `AUTOAXE_MARKET_NETWORK` (the existing private Docker
   network on which the DB hostname is reachable) through deployment secrets
   or the shell. Do not commit real DSNs or print Compose expanded config.

   ```sh
   docker compose -f infra/compose/pizzint.yaml config --quiet
   docker compose -f infra/compose/pizzint.yaml up --build -d
   docker compose -f infra/compose/pizzint.yaml logs --tail 30 pizzint-collector
   ```

   The daemon checks the DB every 10 seconds and reserves at most one request
   per 300 seconds using the DB clock; no missed-slot backfill or immediate
   retry. Same-DB duplicate instances serialize via advisory lock. Restart
   policy is unless-stopped. HTTP 429 respects Retry-After (at least 300s);
   401/403 blocks until a new permission version, no bypass. Invalid response
   never generates a level. Stored observations deduplicate by API timestamp
   and payload; older source times cannot displace newer observations.
4. On the existing authenticated BFF/API configure `AUTOAXE_MARKET_READ_DSN`,
   `AUTOAXE_APP_RUNTIME_DSN` and `AUTOAXE_OWNER_SUBJECT_REF`, with the
   existing HTTPS/OIDC setup. Only the owner can read private data without
   redistribution rights. `GET /api/v1/dashboard/authorized/market/PENTAGON_PIZZA_PIZZINT`
   supplies the latest stored level, API timestamp and collection health to the
   dashboard (DB-only browser refresh, no provider request). The timestamp
   does not prove a new underlying data update. This is a reference indicator,
   not financial or strategic decision data.
5. Stop only this worker: `docker compose -f infra/compose/pizzint.yaml down`.
   It does not delete the external database or network. The fixture stack is
   still offline for external collection, and is not the production deployment.

## Phase 2 approved MEXC REST and official document capture

Use the existing migrated market DB (head `0014_mexc` or later), admin-reviewed
source grants and restricted egress/private market networks. The
`phase2-collectors.yaml` approved profile defaults each service to help output;
it does not grant rights, enable trading or expose a provider endpoint to the web.
MEXC uses a dedicated 300-second reservation; do not add it to the generic
poller. The stored price is a NAS100_USDT perpetual REST observation with UNKNOWN
quality, not a verified live CME quote.

After source rights, private network and runtime DB configuration are verified,
the operator can run the one-shot or explicit daemon command (use `--daemon`
only for an approved ongoing service):

```sh
docker compose -f infra/compose/phase2-collectors.yaml --profile approved config --quiet
docker compose -f infra/compose/phase2-collectors.yaml --profile approved run --rm mexc /app/.venv/bin/python -m autoaxe.entrypoints.mexc_cli --allow-mexc
```

The BOJ/SEC document CLI produces unapproved candidate JSON or references, not
automatic financial values. Use the approved official service or a trusted
runtime environment with `AUTOAXE_SEC_CONTACT` configured for SEC; do not put
administrator DSNs in containers. With source grants and explicit opt-in:

```sh
python -m autoaxe.entrypoints.document_fetch_cli --execute-approved discover-boj 2026
python -m autoaxe.entrypoints.document_fetch_cli --execute-approved discover-sec <CIK>
python -m autoaxe.entrypoints.document_fetch_cli --execute-approved fetch-sec <CIK> <accession>
```

Subcommands share a source reservation (BOJ 3600s, SEC 900s); do not retry to
bypass it. BOJ fetch-boj accepts only official HTML statement URLs, not PDF.
SEC fair-access applies to the total traffic of all SEC clients in deployment.
Inspect and independently approve candidates using `document_review_cli` before
promotion. See the latest Phase 2 session log for constraints and verification.

## Phase 2 Binance QQQ REST and BEA calendar

Use market DB head `0015_qqq` or later. The QQQUSDT perpetual is an
ETF-linked USDT instrument, not the Nasdaq-100 cash index or CME NQ. Its
5-minute snapshots remain UNKNOWN until live/session verification. Obtain a
source approval whose evidence explicitly covers QQQUSDT; the registry gate
is source-level and does not independently validate the product scope. The
dedicated worker requires explicit opt-in; do not add it to the generic poller.
The BEA calendar is the official key-free ICS feed, polled every 21600 seconds.
It does not establish the actual release timestamp or vintage.

After verifying the existing restricted networks, DB and source approvals:

```sh
docker compose -f infra/compose/phase2-collectors.yaml --profile approved run --rm binance-qqq /app/.venv/bin/python -m autoaxe.entrypoints.binance_qqq_cli --allow-binance-qqq
docker compose -f infra/compose/phase2-collectors.yaml --profile approved run --rm official /app/.venv/bin/python -m autoaxe.entrypoints.official_poll_cli --execute-approved --tasks bea_calendar
```

Add `--daemon` only for an approved ongoing service. No provider calls or
production deployment were performed in the implementation session. SSE uses
named heartbeat messages; keep proxy buffering disabled and verify the actual
IdP, TLS, database and proxy configuration before operating it.
