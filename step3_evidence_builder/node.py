from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from embedding_client import DEFAULT_EMBEDDING_BASE_URL, EmbeddingGemmaClient
from pipeline_state import PipelineState
from step3_evidence_builder.contract_builder import build_generation_contract
from step3_evidence_builder.query_planner import build_query_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STEP3_PERSIST_DIR = str((PROJECT_ROOT / "chroma_db").resolve())
DEFAULT_STEP3_COLLECTION = "renderjs_poc_v3"
DEFAULT_EVIDENCE_TOKEN_BUDGET = 3000
SKIP_DOC_IDS: tuple[str, ...] = (
    "rules_api_001",
    "patterns_008",
    "rules_api_007",
    "rules_api_011",
)
DOC_TYPE_PRIORITY: dict[str, int] = {
    "rule": 1,
    "api": 2,
    "pattern": 3,
    "example": 4,
    "glossary": 5,
}


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _get_spec_final(state: PipelineState) -> dict[str, Any]:
    for candidate in (
        getattr(state, "component_spec_final", None),
        state.spec,
        state.component_spec_draft,
        state.spec_draft,
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _get_constraints_bundle(state: PipelineState) -> dict[str, Any]:
    constraints = state.constraints
    if isinstance(constraints, dict):
        return dict(constraints)
    return {}


def _load_collection(
    *,
    persist_dir: str,
    collection_name: str,
    chroma_client: Any | None = None,
) -> Any:
    client = chroma_client or chromadb.PersistentClient(path=str(Path(persist_dir).resolve()))
    return client.get_collection(collection_name)


def _matches_field_groups(metadata: dict[str, Any], field_groups: list[str]) -> bool:
    if not field_groups:
        return True
    observed = set(_split_csv(metadata.get("field_groups")))
    if not observed:
        return True
    return bool(observed & set(field_groups))


def _query_collection(
    *,
    collection: Any,
    query_plan: dict[str, Any],
    embedding_client: EmbeddingGemmaClient,
) -> tuple[int, list[dict[str, Any]]]:
    candidates: dict[str, dict[str, Any]] = {}
    raw_hit_count = 0
    field_groups = list(query_plan.get("field_groups_activated") or [])

    for query in query_plan.get("queries") or []:
        query_text = str(query.get("query_text") or "").strip()
        if not query_text:
            continue
        query_vector = embedding_client.embed_query(query_text)
        doc_type = str((query.get("filter") or {}).get("doc_type") or "").strip()
        where = {"doc_type": doc_type} if doc_type else None
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=max(1, int(query.get("n_results") or 1)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        for index, doc_id in enumerate(ids):
            raw_hit_count += 1
            metadata = dict((metadatas[index] or {})) if index < len(metadatas) else {}
            if not _matches_field_groups(metadata, field_groups):
                continue
            distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 0.0
            candidate = {
                "doc_id": str(doc_id),
                "intent": str(query.get("intent") or ""),
                "content": str(documents[index] or "") if index < len(documents) else "",
                "metadata": metadata,
                "distance": distance,
            }
            existing = candidates.get(candidate["doc_id"])
            if existing is None or (
                int(existing["metadata"].get("priority") or 999),
                float(existing.get("distance") or 0.0),
            ) > (
                int(metadata.get("priority") or DOC_TYPE_PRIORITY.get(str(metadata.get("doc_type") or ""), 999)),
                distance,
            ):
                candidates[candidate["doc_id"]] = candidate
            elif existing is not None:
                intents = _dedupe([str(existing.get("intent") or ""), str(query.get("intent") or "")])
                existing["intent"] = ",".join(intents)

    return raw_hit_count, list(candidates.values())


def _clean_content(text: str) -> str:
    lines = text.splitlines()
    cleaned: list[str] = []
    in_code_block = False
    list_metadata_keys = {
        "field_groups:",
        "api_names:",
        "use_cases:",
        "component_kinds:",
    }
    scalar_metadata_prefixes = (
        "source_policy:",
        "corpus_type:",
        "version:",
    )
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        fence_candidate = stripped.lstrip("\u200b\ufeff")
        if fence_candidate.startswith("```"):
            in_code_block = not in_code_block
            cleaned.append(line)
            index += 1
            continue

        if not in_code_block:
            if stripped in list_metadata_keys:
                index += 1
                while index < len(lines):
                    item = lines[index].strip()
                    if not item:
                        index += 1
                        continue
                    if item.startswith("- "):
                        index += 1
                        continue
                    break
                continue
            if any(stripped.startswith(prefix) for prefix in scalar_metadata_prefixes):
                index += 1
                continue

        cleaned.append(line)
        index += 1

    collapsed: list[str] = []
    previous_blank = False
    for line in cleaned:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        collapsed.append("" if blank else line.rstrip())
        previous_blank = blank
    return "\n".join(collapsed).strip()


def _serialize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata") or {}
    doc_id = str(item.get("doc_id") or "").strip()
    if not doc_id or doc_id in SKIP_DOC_IDS:
        return None
    cleaned_content = _clean_content(str(item.get("content") or ""))
    if not cleaned_content:
        return None
    return {
        "id": doc_id,
        "doc_type": str(metadata.get("doc_type") or "").strip(),
        "field_groups": _split_csv(metadata.get("field_groups")),
        "content": cleaned_content,
    }


def _pack_evidence(candidates: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            int((item.get("metadata") or {}).get("priority") or DOC_TYPE_PRIORITY.get(
                str((item.get("metadata") or {}).get("doc_type") or ""), 999
            )),
            float(item.get("distance") or 0.0),
            str(item.get("doc_id") or ""),
        ),
    )
    items: list[dict[str, Any]] = []
    total_tokens = 0
    filtered_count = 0

    for item in ordered:
        serialized = _serialize_item(item)
        if serialized is None:
            continue
        filtered_count += 1
        token_est = _estimate_tokens(serialized["content"])
        if total_tokens + token_est > budget:
            continue
        items.append(serialized)
        total_tokens += token_est

    return {
        "items": items,
        "stats": {
            "after_filter": int(len(items)),
            "total_content_tokens_est": int(total_tokens),
        },
    }


def step3_node(
    state: PipelineState,
    *,
    persist_dir: str = DEFAULT_STEP3_PERSIST_DIR,
    collection_name: str = DEFAULT_STEP3_COLLECTION,
    embedding_url: str | None = DEFAULT_EMBEDDING_BASE_URL,
    embedding_client: EmbeddingGemmaClient | None = None,
    chroma_client: Any | None = None,
    evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
) -> PipelineState:
    spec_final = _get_spec_final(state)
    constraints = _get_constraints_bundle(state)
    if not spec_final:
        return state.with_updates(
            status="aborted",
            abort_reason="step3_missing_spec",
            errors=[*state.errors, "Step3 requires component_spec.final as input."],
        )

    embedding = embedding_client or EmbeddingGemmaClient(base_url=embedding_url or DEFAULT_EMBEDDING_BASE_URL)
    query_plan = build_query_plan(spec_final, constraints)

    try:
        collection = _load_collection(
            persist_dir=persist_dir,
            collection_name=collection_name,
            chroma_client=chroma_client,
        )
    except Exception as exc:
        return state.with_updates(
            status="aborted",
            abort_reason="step3_collection_unavailable",
            query_plan=query_plan,
            errors=[*state.errors, f"Step3 could not load Chroma collection '{collection_name}': {exc}"],
        )

    raw_hit_count, candidates = _query_collection(
        collection=collection,
        query_plan=query_plan,
        embedding_client=embedding,
    )
    evidence_pack = _pack_evidence(candidates, max(1, int(evidence_token_budget)))
    evidence_pack["stats"].update(
        {
            "raw_retrieved": int(raw_hit_count),
            "after_dedup": int(len(candidates)),
        }
    )

    generation_contract = build_generation_contract(spec_final, constraints, evidence_pack)
    evidence_pack["generation_contract"] = generation_contract

    next_status = state.status
    next_warnings = list(state.warnings)
    if not candidates:
        next_status = "degraded"
        next_warnings.append("Step3 retrieved zero corpus hits; continuing with degraded evidence.")

    return state.with_updates(
        status=next_status,
        query_plan=query_plan,
        evidence_pack=evidence_pack,
        generation_contract=generation_contract,
        warnings=next_warnings,
    )


class EvidenceBuilderNode:
    def __init__(
        self,
        *,
        persist_dir: str = DEFAULT_STEP3_PERSIST_DIR,
        collection: str = DEFAULT_STEP3_COLLECTION,
        embedding_url: str | None = DEFAULT_EMBEDDING_BASE_URL,
        embedding_client: EmbeddingGemmaClient | None = None,
        chroma_client: Any | None = None,
        evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    ) -> None:
        self.persist_dir = persist_dir
        self.collection = collection
        self.embedding_url = embedding_url
        self.embedding_client = embedding_client
        self.chroma_client = chroma_client
        self.evidence_token_budget = evidence_token_budget

    def build(
        self,
        *,
        spec: dict[str, Any],
        constraints_bundle: dict[str, Any] | None,
        unresolved_issues: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state = PipelineState(
            spec=spec,
            constraints=constraints_bundle or {},
            unresolved_issues=list(unresolved_issues or []),
            status="running",
        )
        next_state = step3_node(
            state,
            persist_dir=self.persist_dir,
            collection_name=self.collection,
            embedding_url=self.embedding_url,
            embedding_client=self.embedding_client,
            chroma_client=self.chroma_client,
            evidence_token_budget=self.evidence_token_budget,
        )
        return dict(next_state.evidence_pack or {})
