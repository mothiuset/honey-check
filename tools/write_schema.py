"""Regenera el esquema JSON publicado a partir de los modelos del dominio."""

from __future__ import annotations

import json
from pathlib import Path

from honey_check.domain.inventory import SCHEMA_VERSION, Inventory


def main() -> None:
    target = Path(__file__).parents[1] / "schema" / f"inventory-{SCHEMA_VERSION}.schema.json"
    schema = Inventory.model_json_schema(by_alias=True)
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
