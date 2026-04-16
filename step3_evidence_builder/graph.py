from __future__ import annotations

from typing import Any

from pipeline_state import PipelineState
from step3_evidence_builder.node import (
    DEFAULT_STEP3_COLLECTION,
    DEFAULT_STEP3_PERSIST_DIR,
    step3_node,
)


def _extract_retriever_config(retriever: Any | None) -> tuple[str, str | None]:
    if retriever is None:
        return DEFAULT_STEP3_PERSIST_DIR, None
    store = getattr(retriever, "store", None)
    persist_dir = str(getattr(store, "persist_dir", DEFAULT_STEP3_PERSIST_DIR))
    embeddings = getattr(store, "embeddings", None)
    embedding_url = getattr(embeddings, "url", None)
    return persist_dir, embedding_url


def _build_retrieval_report(
    *,
    collection: str,
    query_plan: dict[str, Any] | None,
    evidence_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    queries = list((query_plan or {}).get("queries") or [])
    items = list((evidence_pack or {}).get("items") or [])
    stats = dict((evidence_pack or {}).get("stats") or {})
    return {
        "collection": collection,
        "query_count": len(queries),
        "hit_count": len(items),
        "total_tokens_est": int(stats.get("total_content_tokens_est") or 0),
        "raw_retrieved": int(stats.get("raw_retrieved") or 0),
        "after_dedup": int(stats.get("after_dedup") or 0),
        "after_filter": int(stats.get("after_filter") or 0),
    }


def run_step3_evidence_builder(
    initial_state: dict[str, Any],
    *,
    retriever: Any | None = None,
    collection: str = DEFAULT_STEP3_COLLECTION,
    recursion_limit: int = 20,
) -> dict[str, Any]:
    del recursion_limit
    persist_dir, embedding_url = _extract_retriever_config(retriever)
    persist_dir = str(initial_state.get("persist_dir") or persist_dir)
    embedding_url = str(initial_state.get("embedding_url") or embedding_url or "").strip() or embedding_url
    pipeline_state = PipelineState(
        run_id=str(initial_state.get("run_id") or ""),
        spec=dict(initial_state.get("spec") or {}),
        constraints=dict(initial_state.get("constraints") or {}),
        unresolved_issues=list(initial_state.get("unresolved_issues") or []),
        status=str(initial_state.get("status") or "running"),
    )
    next_state = step3_node(
        pipeline_state,
        persist_dir=persist_dir,
        collection_name=collection,
        embedding_url=embedding_url or None,
    )
    retrieval_report = _build_retrieval_report(
        collection=collection,
        query_plan=next_state.query_plan,
        evidence_pack=next_state.evidence_pack,
    )
    return {
        **initial_state,
        "query_plan": dict(next_state.query_plan or {}),
        "evidence_pack": dict(next_state.evidence_pack or {}),
        "generation_contract": dict(next_state.generation_contract or {}),
        "retrieval_report": retrieval_report,
        "status": next_state.status,
        "warnings": list(next_state.warnings),
        "errors": list(next_state.errors),
    }
