"""Report installed package metadata only, no provider/network calls."""
from importlib.metadata import metadata, version
import sys


def license_name(name: str) -> str:
    info = metadata(name)
    if info.get("License-Expression"):
        return info["License-Expression"]
    classifiers = [
        item.rsplit(" :: ", 1)[-1]
        for item in info.get_all("Classifier", [])
        if item.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    value = info.get("License", "")
    if value and len(value.strip()) < 120:
        return value.strip()
    return "inspect bundled LICENSE/NOTICE (metadata incomplete)"


for name in sys.argv[1:]:
    print(f"{name} {version(name)} | {license_name(name)}")
