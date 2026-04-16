from __future__ import annotations

from pathlib import Path

import chromadb

from embedding_client import EmbeddingGemmaClient
from pipeline_state import PipelineState
from step3_evidence_builder.contract_builder import build_generation_contract
from step3_evidence_builder.node import step3_node
from step3_evidence_builder.query_planner import build_query_plan
from tests.http_test_server import run_json_server


def _make_state() -> PipelineState:
    return PipelineState(
        run_id="run_step3_test",
        status="running",
        spec={
            "task_type": "form",
            "page_goal": "Create a login form",
            "state_schema": {
                "username": "string",
                "password": "string",
                "loading": "boolean",
                "error": "string",
            },
            "events": [
                {
                    "type": "submit",
                    "selector": ".login-form",
                    "action": "validate_and_submit",
                    "prevent_default": True,
                }
            ],
            "dom_requirements": [
                ".login-form",
                ".username-input",
                ".password-input",
                ".submit-btn",
                ".error-msg",
            ],
            "async_requirements": {"has_async": True, "needs_queue": True},
            "child_gadget_needs": [],
            "acquisition_needs": [],
            "todo_markers": ["TODO: implement actual auth API call"],
        },
        constraints={
            "field_groups_activated": [
                "layout_html",
                "state_logic",
                "event_binding",
                "async_flow",
            ],
            "forbidden_patterns": [
                ".then(",
                "id=",
                "document.querySelector",
            ],
            "must_not_use_global_dom": True,
            "dom_writes_only_in_onstatechange": True,
        },
    )


def _build_collection(tmp_path: Path, collection_name: str = "renderjs_poc_v3") -> chromadb.Collection:
    persist_dir = tmp_path / "chroma_db"
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=["rules_api_001", "rules_api_002", "patterns_001", "code_examples_001"],
        documents=[
            "## Rule: never use .then()\n\nUse RSVP.Queue and avoid Promise.then().",
            "## API: onEvent\n\nUse onEvent submit handler and changeState.",
            "## Pattern: RSVP.Queue submit\n\nReturn new RSVP.Queue().push(...) in form submit handlers.",
            "## Example: login form\n\nA complete login form uses onEvent, changeState, and onStateChange.",
        ],
        metadatas=[
            {
                "doc_id": "rules_api_001",
                "corpus_type": "rules_api",
                "source_file": "renderjs_corpus_api_rules.md",
                "section_title": "Rule: never use .then()",
                "chunk_index": 0,
                "doc_type": "rule",
                "priority": 1,
                "field_groups": "async_flow",
                "api_names": "",
                "use_cases": "general",
                "component_kinds": "",
            },
            {
                "doc_id": "rules_api_002",
                "corpus_type": "rules_api",
                "source_file": "renderjs_corpus_api_rules.md",
                "section_title": "API: onEvent",
                "chunk_index": 1,
                "doc_type": "api",
                "priority": 2,
                "field_groups": "event_binding,async_flow",
                "api_names": "onEvent,changeState",
                "use_cases": "form_submit",
                "component_kinds": "form,page",
            },
            {
                "doc_id": "patterns_001",
                "corpus_type": "patterns",
                "source_file": "renderjs_corpus_patterns.md",
                "section_title": "Pattern: RSVP.Queue submit",
                "chunk_index": 0,
                "doc_type": "pattern",
                "priority": 3,
                "field_groups": "event_binding,async_flow",
                "api_names": "onEvent,changeState",
                "use_cases": "form_submit",
                "component_kinds": "form,page",
            },
            {
                "doc_id": "code_examples_001",
                "corpus_type": "code_examples",
                "source_file": "renderjs_corpus_examples.md",
                "section_title": "Example: login form",
                "chunk_index": 0,
                "doc_type": "example",
                "priority": 4,
                "field_groups": "layout_html,state_logic,event_binding,async_flow",
                "api_names": "onEvent,changeState,onStateChange,setState",
                "use_cases": "form_submit",
                "component_kinds": "form,page",
            },
        ],
        embeddings=[
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
    )
    return collection


def test_build_query_plan_and_contract_are_deterministic() -> None:
    state = _make_state()
    query_plan = build_query_plan(state.spec or {}, state.constraints or {})

    intents = [item["intent"] for item in query_plan["queries"]]
    assert intents == ["rules", "api", "event_pattern", "async_pattern", "example"]

    evidence_pack = {
        "evidence": [
            {
                "content": "## API: onEvent\n\nUse onEvent submit handler and changeState.",
                "metadata": {"doc_type": "api", "api_names": "onEvent,changeState"},
            },
            {
                "content": "## Pattern: RSVP.Queue submit\n\nReturn new RSVP.Queue().push(...)",
                "metadata": {"doc_type": "pattern", "api_names": "onEvent,changeState"},
            },
        ],
        "total_tokens_est": 123,
    }
    contract = build_generation_contract(state.spec or {}, state.constraints or {}, evidence_pack)

    assert contract["allowed_api_names"] == ["RSVP.Queue", "changeState", "onEvent", "onStateChange", "setState"]
    assert contract["forbidden_patterns"] == [".then(", "id=", "document.querySelector"]
    assert contract["required_dom_selectors"] == [".login-form", ".username-input", ".password-input", ".submit-btn", ".error-msg"]
    assert contract["required_state_keys"] == ["error", "loading", "password", "username"]
    assert contract["required_event_bindings"] == ["submit"]
    assert "event_bindings" in contract["required_slots"]
    assert contract["evidence_token_budget"] == 123
    assert contract["recommended_pattern_ids"] == []
    assert contract["unresolved_markers"] == ["TODO: implement actual auth API call"]


def test_build_generation_contract_accepts_list_state_schema_and_trigger_events() -> None:
    spec_final = {
        "task_type": "form",
        "state_schema": [
            {"name": "username", "field_type": "string"},
            {"name": "password", "field_type": "string"},
            {"name": "loading", "field_type": "boolean"},
        ],
        "events": [
            {"trigger": "submit", "name": "on_submit_login_area"},
            {"trigger": "input", "name": "on_input_username"},
        ],
        "dom_requirements": [
            ".login-form",
            {"selector_hint": ".username-input"},
            {"css_selector": ".submit-btn"},
        ],
        "todo_markers": ["TODO: wire auth acquisition"],
        "uncertainties": ["Post-login navigation is unspecified."],
    }
    constraints = {
        "field_groups_activated": ["state_logic", "event_binding"],
        "forbidden_patterns": [".then("],
    }
    contract = build_generation_contract(spec_final, constraints, {"evidence": [], "total_tokens_est": 0})

    assert contract["required_state_keys"] == ["loading", "password", "username"]
    assert contract["required_event_bindings"] == ["submit", "input"]
    assert contract["required_dom_selectors"] == [".login-form", ".username-input", ".submit-btn"]
    assert contract["unresolved_markers"] == [
        "TODO: wire auth acquisition",
        "Post-login navigation is unspecified.",
    ]


def test_build_generation_contract_limits_apis_to_explicit_child_and_acquisition_needs() -> None:
    spec_final = {
        "state_schema": [{"name": "message", "field_type": "string"}],
        "events": [],
        "child_gadget_needs": [{"slot": "preview", "required_methods": ["render"]}],
        "acquisition_needs": [{"acquisition_name": "notify", "methods": ["notifyParent"]}],
        "dom_requirements": [{"selector_hint": ".preview-slot"}],
        "todo_markers": [],
        "uncertainties": [],
    }
    contract = build_generation_contract(
        spec_final,
        {"forbidden_patterns": []},
        {"items": [], "stats": {"total_content_tokens_est": 0}},
    )

    assert contract["allowed_api_names"] == [
        "changeState",
        "declareAcquiredMethod",
        "declareGadget",
        "declareMethod",
        "getDeclaredGadget",
        "onStateChange",
        "ready",
        "setState",
    ]
    assert "allowPublicAcquisition" not in contract["allowed_api_names"]
    assert "getInterfaceList" not in contract["allowed_api_names"]
    assert "getPath" not in contract["allowed_api_names"]


def test_step3_node_uses_query_embeddings_and_builds_contract(tmp_path: Path) -> None:
    _build_collection(tmp_path)

    def responder(path, body):
        assert path == "/embeddings"
        content = body["content"]
        assert content.startswith("task: search result | query: ")
        if "rules" in content:
            return {"embedding": [1.0, 0.0, 0.0]}
        if "API" in content:
            return {"embedding": [0.9, 0.1, 0.0]}
        if "pattern" in content or "RSVP.Queue" in content:
            return {"embedding": [0.0, 1.0, 0.0]}
        return {"embedding": [0.0, 0.0, 1.0]}

    with run_json_server(responder) as (base_url, server_state):
        next_state = step3_node(
            _make_state(),
            persist_dir=str(tmp_path / "chroma_db"),
            collection_name="renderjs_poc_v3",
            embedding_client=EmbeddingGemmaClient(base_url=base_url),
        )

    assert next_state.status == "running"
    assert next_state.query_plan is not None
    assert next_state.evidence_pack is not None
    assert next_state.generation_contract is not None
    assert len(server_state.requests) == len(next_state.query_plan["queries"])
    assert len(next_state.evidence_pack["items"]) >= 2
    assert next_state.evidence_pack["stats"]["total_content_tokens_est"] <= 3000
    assert next_state.evidence_pack["stats"]["raw_retrieved"] >= next_state.evidence_pack["stats"]["after_dedup"]
    assert next_state.evidence_pack["stats"]["after_filter"] == len(next_state.evidence_pack["items"])
    assert next_state.generation_contract["forbidden_patterns"] == [".then(", "id=", "document.querySelector"]
    assert next_state.generation_contract["allowed_api_names"] == ["RSVP.Queue", "changeState", "onEvent", "onStateChange", "setState"]
    assert "recommended_pattern_ids" in next_state.generation_contract
    assert next_state.generation_contract["unresolved_markers"] == ["TODO: implement actual auth API call"]
    assert all("metadata" not in item for item in next_state.evidence_pack["items"])
    assert all("field_groups:" not in item["content"] for item in next_state.evidence_pack["items"])
    assert all(item["id"] not in {"rules_api_001", "rules_api_007", "rules_api_011", "patterns_008"} for item in next_state.evidence_pack["items"])


def test_step3_node_marks_degraded_when_no_hits(tmp_path: Path) -> None:
    persist_dir = tmp_path / "chroma_db"
    client = chromadb.PersistentClient(path=str(persist_dir))
    client.create_collection(name="renderjs_poc_v3", metadata={"hnsw:space": "cosine"})

    def responder(path, body):
        assert path == "/embeddings"
        return {"embedding": [1.0, 0.0, 0.0]}

    with run_json_server(responder) as (base_url, _):
        next_state = step3_node(
            _make_state(),
            persist_dir=str(persist_dir),
            collection_name="renderjs_poc_v3",
            embedding_client=EmbeddingGemmaClient(base_url=base_url),
        )

    assert next_state.status == "degraded"
    assert next_state.evidence_pack is not None
    assert next_state.evidence_pack["items"] == []
    assert "zero corpus hits" in next_state.warnings[-1]
