"""Generate missing local disposable Postgres passwords without printing them."""
from pathlib import Path
from secrets import token_urlsafe

path = Path(__file__).resolve().parents[1] / ".env.phase0"
existing = path.read_text(encoding="utf-8") if path.exists() else ""
keys = {line.split("=", 1)[0] for line in existing.splitlines() if "=" in line}
missing = [
    key for key in ("AUTOAXE_FIXTURE_DB_PASSWORD", "AUTOAXE_FIXTURE_MARKET_READ_PASSWORD",
                    "AUTOAXE_FIXTURE_MARKET_WRITE_PASSWORD") if key not in keys
]
if missing:
    with path.open("a", encoding="utf-8") as file:
        if existing and not existing.endswith("\n"):
            file.write("\n")
        for key in missing:
            file.write(key + "=" + token_urlsafe(32) + "\n")
print("Ignored .env.phase0 ready (fixture only)")
