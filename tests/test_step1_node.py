from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from inference_client import LlamaCppClient
from pipeline_state import PipelineState
from step1_spec_synth.main import resolve_prompt_dump_path, synthesize_component_spec
from step1_spec_synth.node import step1_node
from tests.http_test_server import run_json_server


VALID_DRAFT = {
    "task_type": "display",
    "page_goal": "Display a notice message.",
    "assumptions": ["The notice content is already available."],
    "uncertainties": [],
    "degradation_policy": {
        "mode": "conservative",
        "summary": "Show an empty state when no notice is available.",
    },
    "ui_plan": [
        {
            "area_id": "notice_area",
            "title": "Notice Area",
            "component_kind": "section",
            "purpose": "Display the notice body",
        }
    ],
    "component_whitelist_used": ["page", "section", "empty_state"],
    "state_schema": [
        {
            "name": "notice_text",
            "field_type": "string",
            "default": "",
            "required": True,
            "description": "Notice content",
        }
    ],
    "events": [],
    "dom_requirements": [
        {
            "selector_hint": ".notice-area",
            "element": "section",
            "purpose": "Display the notice text",
            "required": True,
        }
    ],
    "data_requirements": [],
    "async_requirements": [],
    "child_gadget_needs": [],
    "acquisition_needs": [],
    "allowed_degradation": [
        {
            "condition": "the notice is empty",
            "fallback": "show a no notice available message",
        }
    ],
    "todo_markers": [],
}


def _chat_completion_response(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                }
            }
        ]
    }


def _chat_completion_reasoning_response(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": content,
                }
            }
        ]
    }


def test_step1_node_structured_success() -> None:
    def responder(path: str, body: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/chat/completions"
        assert body["temperature"] == 0.1
        assert "response_format" in body
        return _chat_completion_response(json.dumps(VALID_DRAFT, ensure_ascii=False))

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(base_url=base_url)
        result = step1_node(PipelineState(request="Create a notice page."), client=client)

    assert result.status == "ready"
    assert result.abort_reason == ""
    assert result.component_spec_draft == VALID_DRAFT
    assert result.spec_draft == VALID_DRAFT
    assert result.retry_counts["step1"] == 0
    assert sorted(result.prompt_versions) == [
        "step1_fewshots.json",
        "step1_system.md",
        "step1_user_template.md",
    ]
    assert len(state.requests) == 1


def test_step1_node_accepts_reasoning_content_output() -> None:
    def responder(path: str, body: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/chat/completions"
        assert "response_format" in body
        return _chat_completion_reasoning_response(json.dumps(VALID_DRAFT, ensure_ascii=False))

    with run_json_server(responder) as (base_url, _):
        client = LlamaCppClient(base_url=base_url)
        result = step1_node(PipelineState(request="Create a notice page."), client=client)

    assert result.status == "ready"
    assert result.component_spec_draft == VALID_DRAFT
    assert result.retry_counts["step1"] == 0


def test_step1_node_retries_with_plain_text_fallback() -> None:
    responses = iter(
        [
            _chat_completion_response("Here is the result, but it is not pure JSON."),
            _chat_completion_response(f"```json\n{json.dumps(VALID_DRAFT, ensure_ascii=False)}\n```"),
        ]
    )

    def responder(path: str, body: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/chat/completions"
        return next(responses)

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(base_url=base_url)
        result = step1_node(PipelineState(request="Create a notice page."), client=client)

    assert result.status == "ready"
    assert result.abort_reason == ""
    assert result.component_spec_draft == VALID_DRAFT
    assert result.retry_counts["step1"] == 1
    assert len(state.requests) == 2
    assert "response_format" in state.requests[0].body
    assert "response_format" not in state.requests[1].body


def test_step1_node_aborts_after_retry_failure() -> None:
    def responder(path: str, body: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/chat/completions"
        return _chat_completion_response("still not valid json")

    with run_json_server(responder) as (base_url, _):
        client = LlamaCppClient(base_url=base_url)
        result = step1_node(PipelineState(request="Create a notice page."), client=client)

    assert result.status == "aborted"
    assert result.abort_reason == "step1_parse_fail"
    assert result.component_spec_draft is None
    assert result.spec_draft is None
    assert result.retry_counts["step1"] == 1
    assert any("Step1 parse failed after retry" in message for message in result.errors)


def test_synthesize_component_spec_manual_entrypoint() -> None:
    def responder(path: str, body: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/chat/completions"
        return _chat_completion_response(json.dumps(VALID_DRAFT, ensure_ascii=False))

    with run_json_server(responder) as (base_url, state):
        args = type(
            "Args",
            (),
            {
                "request": "Create a notice page.",
                "request_file": None,
                "base_url": base_url,
                "timeout": 30.0,
                "model": "llama.cpp",
                "api_key": "SECRET",
            },
        )()
        draft, report = synthesize_component_spec(args)

    assert draft.model_dump(mode="json") == VALID_DRAFT
    assert report.ok is True
    assert report.status == "ready"
    assert state.requests[0].headers["Authorization"] == "Bearer SECRET"


def test_synthesize_component_spec_requires_api_key() -> None:
    args = type(
        "Args",
        (),
        {
            "request": "Create a notice page.",
            "request_file": None,
            "base_url": "https://example.test",
            "timeout": 30.0,
            "model": "llama.cpp",
            "api_key": None,
            "no_stream": False,
        },
    )()

    try:
        synthesize_component_spec(args)
    except ValueError as exc:
        assert str(exc) == "Step1 requires --api-key for the inference endpoint."
    else:
        raise AssertionError("Expected synthesize_component_spec to reject a missing API key.")


def test_resolve_prompt_dump_path_uses_output_path_stem() -> None:
    with TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / "draft.json"
        args = type(
            "Args",
            (),
            {
                "out": str(output_path),
                "report_out": None,
            },
        )()
        resolved = resolve_prompt_dump_path(args)

    assert resolved.name == "draft.prompt_bundle.json"
