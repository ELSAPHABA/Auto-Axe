"""Deterministic versioned contract generator."""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from autoaxe.adapters.contracts import Event, Workflow
from autoaxe.entrypoints.api import create_app


def documents() -> dict[str, Any]:
    def draft(schema: dict[str, Any]) -> dict[str, Any]:
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}

    return {
        "openapi.json": create_app().openapi(),
        "workflow/v1.schema.json": draft(Workflow.model_json_schema(mode="serialization")),
        "events/v1.schema.json": draft(TypeAdapter(Event).json_schema(mode="serialization")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[5] / "packages/contracts"
    )
    args = parser.parse_args()
    for name, value in documents().items():
        path = args.root / name
        content = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"contract drift: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    print("contract schemas checked" if args.check else "contract schemas generated")


if __name__ == "__main__":
    main()
