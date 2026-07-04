"""Merge duplicate graph entities created by per-chunk extraction."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from domain.entity_glossary import canonical_entity_key as ckey
from neo4j import Session

logger = logging.getLogger(__name__)

DEDUPE_LABELS: tuple[str, ...] = (
    "Material",
    "Process",
    "Equipment",
    "Facility",
    "Team",
    "Expert",
)

# Chunk-level spelling / morphology variants → one canonical key.
_KEY_ALIASES: dict[str, str] = {
    "leached_residue": "leach_residue",
    "leaching_residue": "leach_residue",
    "ferric_sulphate": "ferric_sulfate",
    "sulphuric_acid": "sulfuric_acid",
    "sulphur_dioxide": "sulfur_dioxide",
    "sulphur_trioxide": "sulfur_trioxide",
    "aluminium_hydroxide": "aluminum_hydroxide",
    "nickel_sulphide_ore": "nickel_sulfide_ore",
    "bricks": "brick",
    "flocculent": "flocculant",
}


def dedupe_key(label: str, name: str, stored_key: str = "") -> str:
    """Stable merge key for a graph entity."""
    raw = (stored_key or "").strip()
    key = raw or ckey(name or "")
    if not key:
        return ""
    key = _KEY_ALIASES.get(key, key)
    if label == "Expert":
        key = _normalize_person_key(key)
    return key


def _normalize_person_key(key: str) -> str:
    return re.sub(r"\.+", ".", key.replace(" ", "_")).strip("_")


def _pick_keeper(session: Session, label: str, ids: list[str]) -> tuple[str, list[str]]:
    rows = session.run(
        f"""
        UNWIND $ids AS nid
        MATCH (n:{label} {{id: nid}})
        OPTIONAL MATCH (n)-[r]-()
        RETURN n.id AS id, count(r) AS degree
        ORDER BY degree DESC, n.id
        """,
        {"ids": ids},
    )
    ordered = [str(row["id"]) for row in rows]
    if not ordered:
        return ids[0], ids[1:]
    keeper = ordered[0]
    return keeper, [node_id for node_id in ordered[1:] if node_id != keeper]


def _merge_with_apoc(session: Session, label: str, keeper_id: str, dup_ids: list[str]) -> str | None:
    ordered_ids = [keeper_id] + [i for i in dup_ids if i != keeper_id]
    record = session.run(
        f"""
        UNWIND $ids AS nid
        WITH nid, apoc.coll.indexOf($ids, nid) AS ord
        ORDER BY ord
        MATCH (n:{label} {{id: nid}})
        WITH collect(n) AS nodes
        CALL apoc.refactor.mergeNodes(nodes, {{
            properties: 'overwrite',
            mergeRels: true
        }})
        YIELD node
        RETURN node.id AS id
        """,
        {"ids": ordered_ids},
    ).single()
    return str(record["id"]) if record and record["id"] else keeper_id


def _redirect_node(session: Session, label: str, dup_id: str, keeper_id: str) -> None:
    session.run(
        f"""
        MATCH (keeper:{label} {{id: $keeper_id}})
        MATCH (dup:{label} {{id: $dup_id}})
        WITH keeper, dup
        CALL apoc.refactor.mergeNodes([keeper, dup], {{
            properties: 'overwrite',
            mergeRels: true
        }})
        YIELD node
        RETURN node.id AS id
        """,
        {"dup_id": dup_id, "keeper_id": keeper_id},
    )


def _merge_group(session: Session, label: str, key: str, ids: list[str]) -> dict | None:
    unique_ids = list(dict.fromkeys(ids))
    if len(unique_ids) < 2:
        return None

    keeper_id, dup_ids = _pick_keeper(session, label, unique_ids)
    if not dup_ids:
        return None

    merged_ids = list(dup_ids)
    try:
        keeper_id = _merge_with_apoc(session, label, keeper_id, dup_ids) or keeper_id
    except Exception as exc:
        logger.warning("APOC merge failed for %s (%s): %s", label, key, exc)
        for dup_id in dup_ids:
            try:
                _redirect_node(session, label, dup_id, keeper_id)
            except Exception as inner:
                logger.warning(
                    "Manual merge failed for %s dup=%s keeper=%s: %s",
                    label,
                    dup_id,
                    keeper_id,
                    inner,
                )
                merged_ids = [i for i in merged_ids if i != dup_id]

    display_name = next(
        (
            row["name"]
            for row in session.run(
                f"MATCH (n:{label} {{id: $id}}) RETURN n.name AS name",
                {"id": keeper_id},
            )
            if row["name"]
        ),
        key.replace("_", " "),
    )

    session.run(
        f"""
        MATCH (n:{label} {{id: $keeper_id}})
        SET n.canonical_key = $key,
            n.name = coalesce(n.name, $display_name)
        """,
        {"keeper_id": keeper_id, "key": key, "display_name": display_name},
    )

    return {
        "label": label,
        "canonical_key": key,
        "keeper_id": keeper_id,
        "merged_ids": [i for i in merged_ids if i != keeper_id],
    }


def _coerce_name(value) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _backfill_canonical_keys(session: Session, label: str) -> int:
    rows = list(
        session.run(
            f"MATCH (n:{label}) RETURN n.id AS id, n.name AS name, coalesce(n.canonical_key, '') AS ck"
        )
    )
    updated = 0
    for row in rows:
        name = _coerce_name(row["name"])
        if isinstance(row["name"], list) and name:
            session.run(
                f"MATCH (n:{label} {{id: $id}}) SET n.name = $name",
                {"id": row["id"], "name": name},
            )
        key = dedupe_key(label, name, row["ck"] or "")
        if not key or key == (row["ck"] or ""):
            continue
        session.run(
            f"MATCH (n:{label} {{id: $id}}) SET n.canonical_key = $key",
            {"id": row["id"], "key": key},
        )
        updated += 1
    return updated


def _fuzzy_merge_pass(session: Session, label: str, *, threshold: float = 0.96) -> list[dict]:
    rows = list(
        session.run(
            f"MATCH (n:{label}) RETURN n.id AS id, n.name AS name ORDER BY toLower(n.name)"
        )
    )
    merged: list[dict] = []
    used: set[str] = set()

    for i, a in enumerate(rows):
        aid = str(a["id"])
        if aid in used:
            continue
        name_a = (a["name"] or "").strip()
        if not name_a:
            continue
        group_ids = [aid]

        for b in rows[i + 1 : i + 40]:
            bid = str(b["id"])
            if bid in used:
                continue
            name_b = (b["name"] or "").strip()
            if not name_b:
                continue
            ratio = SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()
            if ratio < threshold:
                if len(name_b) > len(name_a) + 4:
                    break
                continue
            ka = dedupe_key(label, name_a)
            kb = dedupe_key(label, name_b)
            if ka and kb and ka == kb:
                group_ids.append(bid)
                continue
            shorter, longer = sorted([name_a.lower(), name_b.lower()], key=len)
            if shorter in longer or ratio >= 0.985:
                group_ids.append(bid)

        if len(group_ids) < 2:
            continue

        key = dedupe_key(label, name_a) or ckey(name_a)
        result = _merge_group(session, label, key, group_ids)
        if result:
            merged.append(result)
            used.update(group_ids)

    return merged


def reconcile_duplicate_entities(session: Session) -> dict:
    """Find duplicate entity nodes and merge them in Neo4j."""
    backfilled: dict[str, int] = {}
    merged_groups: list[dict] = []

    for label in DEDUPE_LABELS:
        backfilled[label] = _backfill_canonical_keys(session, label)

        rows = list(
            session.run(
                f"MATCH (n:{label}) "
                "RETURN n.id AS id, n.name AS name, coalesce(n.canonical_key, '') AS ck"
            )
        )
        groups: dict[str, list[str]] = {}
        for row in rows:
            name = _coerce_name(row["name"])
            key = dedupe_key(label, name, row["ck"] or "")
            if not key:
                continue
            groups.setdefault(key, []).append(str(row["id"]))

        for key, ids in groups.items():
            if len(ids) < 2:
                continue
            result = _merge_group(session, label, key, ids)
            if result:
                merged_groups.append(result)

        if label in ("Material", "Process", "Equipment", "Facility"):
            merged_groups.extend(_fuzzy_merge_pass(session, label))

    return {
        "backfilled_keys": backfilled,
        "merged_group_count": len(merged_groups),
        "merged_node_count": sum(len(g.get("merged_ids") or []) for g in merged_groups),
        "groups": merged_groups[:200],
    }
