"""Repair Expert/Team nodes whose id was corrupted by property combine during merge."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from settings import get_settings
from storage.graph_db import GraphDB

_UUID_LIST_RE = re.compile(
    r"^\['(?P<a>[0-9a-f\-]{36})',\s*'(?P<b>[0-9a-f\-]{36})'\]$"
)


def _parse_corrupted_id(raw) -> str | None:
    if isinstance(raw, list) and raw:
        return str(raw[0])
    if isinstance(raw, str):
        match = _UUID_LIST_RE.match(raw.strip())
        if match:
            return match.group("a")
    return None


def main() -> None:
    db = GraphDB(get_settings())
    fixed = 0
    with db.driver.session() as session:
        for label in ("Expert", "Team"):
            rows = list(
                session.run(
                    f"MATCH (n:{label}) RETURN elementId(n) AS eid, n.id AS id"
                )
            )
            for row in rows:
                keeper = _parse_corrupted_id(row["id"])
                if not keeper:
                    continue
                session.run(
                    f"""
                    MATCH (n:{label})
                    WHERE elementId(n) = $eid
                    SET n.id = $keeper
                    """,
                    {"eid": row["eid"], "keeper": keeper},
                )
                fixed += 1
    print(f"fixed corrupted id properties: {fixed}")


if __name__ == "__main__":
    main()
