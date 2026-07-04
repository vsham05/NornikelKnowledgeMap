"""Inspect duplicate entity groups in Neo4j."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from domain.entity_glossary import canonical_entity_key as ckey
from settings import get_settings
from storage.graph_db import GraphDB


def main() -> None:
    db = GraphDB(get_settings())
    labels = ["Material", "Process", "Equipment", "Facility", "Team", "Expert"]
    with db.driver.session() as session:
        for label in labels:
            rows = list(
                session.run(
                    f"MATCH (n:{label}) "
                    "RETURN n.id AS id, n.name AS name, coalesce(n.canonical_key, '') AS ck"
                )
            )
            groups: dict[str, list[tuple[str, str]]] = {}
            for row in rows:
                raw_name = row["name"]
                if isinstance(raw_name, list):
                    name = next((str(x).strip() for x in raw_name if str(x).strip()), "")
                else:
                    name = str(raw_name or "")
                key = ckey(name) or (row["ck"] or "").strip()
                if not key:
                    continue
                groups.setdefault(key, []).append((str(row["id"]), name))
            dups = {k: v for k, v in groups.items() if len(v) > 1}
            if not dups:
                print(f"{label}: no duplicates by canonical key")
                continue
            extra = sum(len(v) - 1 for v in dups.values())
            print(
                f"{label}: {len(dups)} groups, {extra} extra nodes "
                f"(total {len(rows)})"
            )
            for key, items in list(dups.items())[:10]:
                print(f"  {key}: {[n for _, n in items]}")


if __name__ == "__main__":
    main()
