"""Decide whether to create, replace, or skip document ingestion."""

from __future__ import annotations

import logging

from domain.dto.document import DocumentDTO
from ingestion.dedup import DedupDecision, hash_document_text
from storage.graph_db import GraphDB

logger = logging.getLogger(__name__)


class DocumentDedupService:
    def __init__(self, graph_db: GraphDB):
        self.graph_db = graph_db

    def purge_document_ids(self, document_ids: list[str], vector_db=None) -> int:
        removed = 0
        for doc_id in document_ids:
            if self.graph_db.delete_document(doc_id):
                removed += 1
                if vector_db is not None:
                    try:
                        vector_db.delete_document_chunks(doc_id)
                    except Exception as exc:
                        logger.warning(f"Vector cleanup for {doc_id}: {exc}")
        return removed

    def consolidate_matches(
        self,
        matches: list[dict],
        vector_db=None,
    ) -> dict | None:
        """Keep the newest document, purge older clones."""
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]

        keeper = matches[0]
        duplicate_ids = [doc["id"] for doc in matches[1:] if doc["id"] != keeper["id"]]
        if duplicate_ids:
            removed = self.purge_document_ids(duplicate_ids, vector_db)
            logger.info(f"Purged {removed} duplicate document clone(s), kept {keeper['id']}")
        return keeper

    def decide_for_file(
        self,
        file_hash: str,
        document: DocumentDTO,
        vector_db=None,
    ) -> DedupDecision:
        content_hash = hash_document_text(document)

        by_hash = self.graph_db.find_all_documents_by_file_hash(file_hash)
        keeper = self.consolidate_matches(by_hash, vector_db)
        if keeper:
            existing_hash = keeper.get("content_hash")
            if existing_hash is None or existing_hash == content_hash:
                return DedupDecision(
                    "skip",
                    keeper["id"],
                    "This file is already indexed (unchanged).",
                )
            return DedupDecision(
                "replace",
                keeper["id"],
                "File changed — replacing previous version.",
            )

        if document.file_path:
            by_name = self.graph_db.find_all_documents_by_filename(document.file_path)
            keeper = self.consolidate_matches(by_name, vector_db)
            if keeper:
                return DedupDecision(
                    "skip",
                    keeper["id"],
                    f"This file is already indexed as '{document.file_path}'.",
                )

        by_content = self.graph_db.find_all_documents_by_content_hash(content_hash)
        keeper = self.consolidate_matches(by_content, vector_db)
        if keeper:
            return DedupDecision(
                "skip",
                keeper["id"],
                f"Duplicate content already indexed: {keeper.get('title', 'document')}",
            )

        return DedupDecision("create", None, "New document.")

    def decide_for_url(
        self,
        canonical_source: str,
        document: DocumentDTO,
        vector_db=None,
    ) -> DedupDecision:
        content_hash = hash_document_text(document)

        matches = self.graph_db.find_all_documents_by_source(canonical_source)
        keeper = self.consolidate_matches(matches, vector_db)
        if keeper:
            existing_hash = keeper.get("content_hash")
            if existing_hash is None or existing_hash == content_hash:
                return DedupDecision(
                    "skip",
                    keeper["id"],
                    "This URL is already indexed.",
                )
            return DedupDecision(
                "replace",
                keeper["id"],
                "URL content changed — replacing previous version.",
            )

        by_content = self.graph_db.find_all_documents_by_content_hash(content_hash)
        keeper = self.consolidate_matches(by_content, vector_db)
        if keeper:
            return DedupDecision(
                "skip",
                keeper["id"],
                f"Same content already indexed from another source: {keeper.get('title', 'document')}",
            )

        return DedupDecision("create", None, "New document.")


def cleanup_duplicate_documents(graph_db: GraphDB, vector_db) -> dict:
    """Remove clone documents, keeping the newest entry per fingerprint group."""
    docs = graph_db.list_document_fingerprints()
    groups: dict[str, list[dict]] = {}

    def add_to_group(key: str | None, doc: dict) -> None:
        if not key:
            return
        groups.setdefault(key, []).append(doc)

    from ingestion.dedup import canonicalize_url

    for doc in docs:
        add_to_group(doc.get("canonical_source"), doc)
        add_to_group(doc.get("file_hash"), doc)
        add_to_group(doc.get("content_hash"), doc)
        if doc.get("file_path"):
            add_to_group(f"path:{doc['file_path']}", doc)
            add_to_group(f"canonical:{canonicalize_url(doc['file_path'])}", doc)

    removed: list[str] = []
    kept: list[str] = []

    for _key, members in groups.items():
        if len(members) < 2:
            continue
        unique = {m["id"]: m for m in members}
        sorted_docs = sorted(
            unique.values(),
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        keeper = sorted_docs[0]
        kept.append(keeper["id"])
        for duplicate in sorted_docs[1:]:
            if duplicate["id"] == keeper["id"]:
                continue
            graph_db.delete_document(duplicate["id"])
            try:
                vector_db.delete_document_chunks(duplicate["id"])
            except Exception:
                pass
            removed.append(duplicate["id"])

    return {
        "removed_count": len(set(removed)),
        "removed_ids": sorted(set(removed)),
        "kept_ids": sorted(set(kept)),
    }
