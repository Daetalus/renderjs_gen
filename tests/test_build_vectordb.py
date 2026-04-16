from __future__ import annotations

from pathlib import Path

import chromadb
import pytest

from scripts.build_vectordb import (
    build_vector_db,
    check_embedding_service,
    format_chunk_id,
    parse_chunk_metadata,
    parse_corpus_file,
    split_h2_sections,
)
from tests.http_test_server import run_json_server


def test_split_h2_sections_skips_code_fence_headings() -> None:
    markdown = """# Corpus

## Real Section
alpha

```js
## Not A Section
console.log("x");
```

## Another Section
beta
"""

    sections = split_h2_sections(markdown)

    assert sections == [
        ("Real Section", 'alpha\n\n```js\n## Not A Section\nconsole.log("x");\n```'),
        ("Another Section", "beta"),
    ]


def test_split_h2_sections_skips_zero_width_code_fence_headings() -> None:
    markdown = "# Corpus\n\n## Real Section\nalpha\n\n\u200b```js\n## Not A Section\nconsole.log('x');\n\u200b```\n\n## Another Section\nbeta\n"

    sections = split_h2_sections(markdown)

    assert sections == [
        ("Real Section", "alpha\n\n\u200b```js\n## Not A Section\nconsole.log('x');\n\u200b```"),
        ("Another Section", "beta"),
    ]


def test_parse_corpus_file_and_chunk_metadata_use_markdown_headers(tmp_path: Path) -> None:
    corpus_text = """# RenderJS Corpus: patterns
version: 3.0
corpus_type: patterns

## Pattern: submit flow
field_groups:
- event_binding
- async_flow
api_names:
- onEvent
- changeState
use_cases:
- form_submit
component_kinds:
- form
- page

Implementation:
- return RSVP.Queue
"""
    corpus_path = tmp_path / "renderjs_corpus_patterns.md"
    corpus_path.write_text(corpus_text, encoding="utf-8")
    try:
        corpus_file = parse_corpus_file(corpus_path)
        metadata = parse_chunk_metadata(split_h2_sections(corpus_file.content)[0][1])
    finally:
        corpus_path.unlink(missing_ok=True)

    assert corpus_file.corpus_type == "patterns"
    assert metadata == {
        "field_groups": ["event_binding", "async_flow"],
        "api_names": ["onEvent", "changeState"],
        "use_cases": ["form_submit"],
        "component_kinds": ["form", "page"],
    }


def test_build_vector_db_indexes_corpus_with_real_chroma(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "renderjs_corpus_api_rules.md").write_text(
        "# API Rules\nversion: 3.0\ncorpus_type: rules_api\n\n## Rule: base rule\nfield_groups:\n- state_logic\nuse_cases:\n- general\n\nRule body.\n\n## API: declareMethod\nfield_groups:\n- state_logic\napi_names:\n- declareMethod\nuse_cases:\n- general\ncomponent_kinds:\n- widget\n\nUse `declareMethod` for state updates.\n",
        encoding="utf-8",
    )
    (corpus_dir / "renderjs_corpus_patterns.md").write_text(
        "# Patterns\nversion: 3.0\ncorpus_type: patterns\n\n## Form Pattern\nfield_groups:\n- event_binding\napi_names:\n- onEvent\n- changeState\nuse_cases:\n- login_form\ncomponent_kinds:\n- form\n- page\n\nUse onEvent submit and changeState for a login form.\n",
        encoding="utf-8",
    )
    (corpus_dir / "renderjs_corpus_examples.md").write_text(
        "# Examples\nversion: 3.0\ncorpus_type: code_examples\n\n## Dashboard Example\nfield_groups:\n- async_flow\napi_names:\n- onStateChange\nuse_cases:\n- dashboard\ncomponent_kinds:\n- dashboard\n- page\n\nExample with RSVP.Queue and onStateChange for a dashboard page.\n",
        encoding="utf-8",
    )
    (corpus_dir / "renderjs_corpus_glossary.md").write_text(
        "# Glossary\nversion: 3.0\ncorpus_type: glossary_templates\n\n## Child Gadget\nfield_groups:\n- child_gadget\nuse_cases:\n- child_gadget_container\ncomponent_kinds:\n- widget\n- child\n\nA child gadget uses data-gadget-url.\n",
        encoding="utf-8",
    )
    persist_dir = tmp_path / "chroma_db"

    def responder(path, body):
        assert path == "/embeddings"
        content = body["content"]
        if content == "title: healthcheck | text: RenderJS vector DB healthcheck":
            return {"embedding": [0.9, 0.1]}
        if "Rule: base rule" in content:
            return {"embedding": [0.8, 0.2]}
        if "API: declareMethod" in content:
            return {"embedding": [1.0, 0.0]}
        if "Form Pattern" in content:
            return {"embedding": [0.0, 1.0]}
        if "Dashboard Example" in content:
            return {"embedding": [0.5, 0.5]}
        if "Child Gadget" in content:
            return {"embedding": [0.2, 0.8]}
        raise AssertionError(f"unexpected content: {content}")

    with run_json_server(responder) as (base_url, state):
        report = build_vector_db(
            corpus_dir=corpus_dir,
            persist_dir=persist_dir,
            embedding_url=base_url,
        )

    assert state.requests[0].body["content"] == "title: healthcheck | text: RenderJS vector DB healthcheck"
    assert report["collection"] == "renderjs_poc_v3"
    assert report["chunk_count"] == 5

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_collection("renderjs_poc_v3")
    payload = collection.get(include=["documents", "metadatas"])

    assert len(payload["ids"]) == 5
    metadata_by_title = {
        item["section_title"]: item
        for item in payload["metadatas"]
    }
    ids_by_title = {
        title: item["doc_id"]
        for title, item in metadata_by_title.items()
    }
    assert ids_by_title["Rule: base rule"] == "rules_api_001"
    assert ids_by_title["API: declareMethod"] == "rules_api_002"
    assert metadata_by_title["Rule: base rule"]["doc_type"] == "rule"
    assert metadata_by_title["Rule: base rule"]["priority"] == 1
    assert metadata_by_title["API: declareMethod"]["doc_type"] == "api"
    assert metadata_by_title["API: declareMethod"]["corpus_type"] == "rules_api"
    assert metadata_by_title["API: declareMethod"]["priority"] == 2
    assert metadata_by_title["API: declareMethod"]["api_names"] == "declareMethod"
    assert metadata_by_title["API: declareMethod"]["use_cases"] == "general"
    assert metadata_by_title["Form Pattern"]["doc_type"] == "pattern"
    assert metadata_by_title["Form Pattern"]["use_cases"] == "login_form"
    assert metadata_by_title["Form Pattern"]["component_kinds"] == "form,page"
    assert metadata_by_title["Dashboard Example"]["priority"] == 4
    assert metadata_by_title["Dashboard Example"]["corpus_type"] == "code_examples"
    assert metadata_by_title["Dashboard Example"]["component_kinds"] == "dashboard,page"
    assert ids_by_title["Dashboard Example"] == "code_examples_001"
    assert metadata_by_title["Child Gadget"]["corpus_type"] == "glossary_templates"
    assert ids_by_title["Child Gadget"] == "glossary_templates_001"
    assert metadata_by_title["Child Gadget"]["field_groups"] == "child_gadget"
    assert payload["documents"][0].startswith("## ")


def test_check_embedding_service_raises_clear_error() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        check_embedding_service("http://127.0.0.1:1")

    message = str(exc_info.value)
    assert "EmbeddingGemma service is unavailable" in message
    assert "http://127.0.0.1:1" in message
