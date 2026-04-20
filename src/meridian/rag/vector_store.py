"""ChromaDB vector store for rules and lessons."""

from __future__ import annotations

import logging

from meridian.config import get_chroma_path

logger = logging.getLogger(__name__)

_RULES_COLLECTION = "meridian_rules"
_LESSONS_COLLECTION = "meridian_lessons"

_client: object | None = None


def reset_client() -> None:
    """Reset the cached ChromaDB client (useful for testing)."""
    global _client
    _client = None


def _get_client() -> object:
    """Lazy-initialize the persistent ChromaDB client."""
    global _client
    if _client is not None:
        return _client

    import chromadb

    chroma_path = get_chroma_path()
    chroma_path.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(chroma_path))
    return _client


def _get_collection(name: str) -> object:
    """Return a ChromaDB collection by name."""
    client = _get_client()
    return client.get_or_create_collection(name=name)


def chromadb_available() -> bool:
    """Return True if the chroma directory exists and has at least one document."""
    try:
        chroma_path = get_chroma_path()
        if not chroma_path.exists():
            return False

        rules_col = _get_collection(_RULES_COLLECTION)
        lessons_col = _get_collection(_LESSONS_COLLECTION)
        return bool(rules_col.count() > 0 or lessons_col.count() > 0)
    except Exception:
        return False


def upsert_rule(
    rule_id: str,
    text: str,
    embedding: list[float],
    metadata: dict,
) -> None:
    """Insert or update a rule in the vector store."""
    collection = _get_collection(_RULES_COLLECTION)
    collection.upsert(
        ids=[rule_id],
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata],
    )


def search_rules(
    query_embedding: list[float],
    scope_ids: list[str],
    top_k: int = 20,
) -> list[dict]:
    """Semantic search over rules filtered by scope_id."""
    collection = _get_collection(_RULES_COLLECTION)
    where_filter = {"scope_id": {"$in": scope_ids}}
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["metadatas", "documents", "distances"],
    )

    output: list[dict] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for idx, doc_id in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        output.append(
            {
                "id": doc_id,
                "text": documents[idx] if idx < len(documents) else "",
                "distance": distances[idx] if idx < len(distances) else None,
                "metadata": meta,
            }
        )
    return output


def upsert_lesson(
    lesson_id: str,
    text: str,
    embedding: list[float],
    metadata: dict,
) -> None:
    """Insert or update a lesson in the vector store."""
    collection = _get_collection(_LESSONS_COLLECTION)
    collection.upsert(
        ids=[lesson_id],
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata],
    )


def search_lessons(
    query_embedding: list[float],
    scope_ids: list[str],
    top_k: int = 20,
) -> list[dict]:
    """Semantic search over lessons filtered by scope_id."""
    collection = _get_collection(_LESSONS_COLLECTION)
    where_filter = {"scope_id": {"$in": scope_ids}}
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["metadatas", "documents", "distances"],
    )

    output: list[dict] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for idx, doc_id in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        output.append(
            {
                "id": doc_id,
                "text": documents[idx] if idx < len(documents) else "",
                "distance": distances[idx] if idx < len(distances) else None,
                "metadata": meta,
            }
        )
    return output
