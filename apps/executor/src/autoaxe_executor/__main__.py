"""Credential-free import smoke; never constructs a broker client."""
from importlib.metadata import version
import os


def smoke() -> str:
    if os.getenv("AUTOAXE_ENVIRONMENT", "fixture") != "fixture":
        raise RuntimeError("executor disabled outside fixture")
    if os.getenv("AUTOAXE_LIVE_ENABLED", "false").lower() != "false":
        raise RuntimeError("LIVE disabled")
    import nhplug  # noqa: F401
    return version("nhplug")


if __name__ == "__main__":
    print(f"Executor disabled; SDK import only: {smoke()}")
