# Phase 0 contracts

Generated: `openapi.json`, `workflow/v1.schema.json`, `events/v1.schema.json`, `generated/api.ts`.
Canonical source is `apps/backend/src/autoaxe/adapters/contracts.py` and fixture routes; never edit generated files manually.
Generate with `uv run --project apps/backend python -m autoaxe.adapters.schema` then `pnpm contracts:types`.
Phase 0 graph has two example node types and event schema has two example events only. Full domain catalogs and durable authorization/idempotency/transactions are subsequent phases. No trading capability.
