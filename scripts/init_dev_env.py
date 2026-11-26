"""Generate a local disposable Postgres password without printing it."""
from pathlib import Path
from secrets import token_urlsafe

path = Path(__file__).resolve().parents[1] / ".env.phase0"
with path.open("x", encoding="utf-8") as file:
    file.write("AUTOAXE_FIXTURE_DB_PASSWORD=" + token_urlsafe(32) + "\n")
print("Created ignored .env.phase0 (fixture only)")
