"""Run entity deduplication against Neo4j."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from settings import get_settings
from storage.graph_db import GraphDB


def main() -> None:
    db = GraphDB(get_settings())
    result = db.reconcile_duplicate_entities()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
