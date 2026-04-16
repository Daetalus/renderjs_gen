from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from pydantic import ValidationError

from inference_client import InferenceClient, InferenceClientError, LlamaCppClient
from pipeline_state import PipelineState
from step1_spec_synth.json_extract import extract_json_object_text
from step1_spec_synth.schema import COMPONENT_SPEC_DRAFT_JSON_SCHEMA, ComponentSpecDraft


LOGGER = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
STEP1_SYSTEM_PATH = PROMPTS_DIR / "step1_system.md"
STEP1_FEWSHOTS_PATH = PROMPTS_DIR / "step1_fewshots.json"
STEP1_USER_TEMPLATE_PATH = PROMPTS_DIR / "step1_user_template.md"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_prompt(prompts_dir: str, filename: str) -> str:
    path = os.path.join(prompts_dir, filename)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def _load_prompt_with_hash(prompts_dir: str, filename: str) -> tuple[str, str]:
    text = _load_prompt(prompts_dir, filename)
    return text, _sha256_text(text)


def _load_fewshots(prompts_dir: str, filename: str) -> tuple[list[dict[str, Any]], str]:
    text, digest = _load_prompt_with_hash(prompts_dir, filename)
    payload = json.loads(text or "[]")
    if not isinstance(payload, list):
        raise ValueError(f"Few-shot file must be a JSON array: {filename}")
    return payload, digest


def _render_user_message(template: str, requirement: str) -> str:
    return template.replace("{{requirement}}", requirement)


def _build_messages(requirement: str, prompts_dir: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    system_prompt, system_sha = _load_prompt_with_hash(prompts_dir, "step1_system.md")
    user_template, user_sha = _load_prompt_with_hash(prompts_dir, "step1_user_template.md")
    fewshots, fewshots_sha = _load_fewshots(prompts_dir, "step1_fewshots.json")

    if not fewshots:
        raise ValueError("Step1 few-shot file is empty.")

    first_example = fewshots[0]
    input_text = str(first_example.get("input") or "").strip()
    output_payload = first_example.get("output")
    if not input_text or not isinstance(output_payload, dict):
        raise ValueError("Invalid Step1 few-shot example at index 1")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Requirement:\n{input_text}"},
        {"role": "assistant", "content": json.dumps(output_payload, ensure_ascii=False)},
        {"role": "user", "content": _render_user_message(user_template, requirement)},
    ]

    prompt_versions = {
        "step1_system.md": system_sha,
        "step1_fewshots.json": fewshots_sha,
        "step1_user_template.md": user_sha,
    }
    return messages, prompt_versions


def _parse_payload(raw_text: str) -> dict[str, Any]:
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("Step1 response JSON must be an object.")
    draft = ComponentSpecDraft.model_validate(payload)
    return draft.model_dump(mode="json")


def _append_error(errors: list[str], message: str) -> list[str]:
    return [*errors, message]


def _emit_progress(progress: Any, message: str) -> None:
    if progress is not None:
        progress(message)


def _emit_raw_output(raw_output: Any, phase: str, text: str) -> None:
    if raw_output is not None:
        raw_output(phase, text)


def _emit_prompt_bundle(prompt_bundle_callback: Any, bundle: dict[str, Any]) -> None:
    if prompt_bundle_callback is not None:
        prompt_bundle_callback(bundle)


def step1_node(
    state: PipelineState,
    client: InferenceClient | None = None,
    *,
    progress: Any | None = None,
    stream_callback: Any | None = None,
    raw_output_callback: Any | None = None,
    prompt_bundle_callback: Any | None = None,
) -> PipelineState:
    requirement = state.request.strip()
    if not requirement:
        return state.with_updates(
            status="aborted",
            abort_reason="step1_missing_request",
            errors=_append_error(state.errors, "Step1 request is empty."),
        )

    prompt_started = time.perf_counter()
    _emit_progress(progress, "Loading Step1 prompts and few-shots")
    messages, prompt_versions = _build_messages(requirement, str(PROMPTS_DIR))
    prompt_elapsed_ms = (time.perf_counter() - prompt_started) * 1000.0
    _emit_progress(
        progress,
        f"Loaded prompts in {prompt_elapsed_ms:.1f} ms; assembled {len(messages)} chat messages",
    )
    _emit_prompt_bundle(
        prompt_bundle_callback,
        {
            "requirement": requirement,
            "messages": messages,
            "json_schema": COMPONENT_SPEC_DRAFT_JSON_SCHEMA,
            "prompt_versions": prompt_versions,
        },
    )

    retry_counts = dict(state.retry_counts)
    merged_prompt_versions = {**state.prompt_versions, **prompt_versions}
    inference_client = client or LlamaCppClient()
    structured_stream = False
    retry_stream = stream_callback is not None
    _emit_progress(
        progress,
        "Structured JSON-schema mode uses non-stream request to improve compatibility and JSON success rate",
    )

    try:
        structured_started = time.perf_counter()
        _emit_progress(progress, "Calling LLM in structured JSON-schema mode")
        raw_text = inference_client.complete(
            messages=messages,
            temperature=0.1,
            json_schema=COMPONENT_SPEC_DRAFT_JSON_SCHEMA,
            stream=structured_stream,
            on_token=None,
            on_event=(None if progress is None else lambda message: progress(f"[llm] {message}")),
        )
        structured_elapsed_ms = (time.perf_counter() - structured_started) * 1000.0
        _emit_progress(
            progress,
            f"Structured LLM call finished in {structured_elapsed_ms:.1f} ms; received {len(raw_text)} chars",
        )
        _emit_progress(progress, "Structured raw LLM output captured; printing before parse")
        _emit_raw_output(raw_output_callback, "structured", raw_text)
        validation_started = time.perf_counter()
        _emit_progress(progress, "Validating structured JSON response against ComponentSpecDraft")
        validated_payload = _parse_payload(raw_text)
        validation_elapsed_ms = (time.perf_counter() - validation_started) * 1000.0
        _emit_progress(progress, f"Structured validation finished in {validation_elapsed_ms:.1f} ms")
    except (InferenceClientError, ValidationError, ValueError, json.JSONDecodeError) as first_error:
        LOGGER.warning("step1 structured parse failed, retrying in plain-text mode: %s", first_error)
        _emit_progress(progress, f"Structured mode failed: {first_error}")
        retry_counts["step1"] = retry_counts.get("step1", 0) + 1
        try:
            retry_started = time.perf_counter()
            _emit_progress(progress, "Retrying once in plain-text mode and extracting JSON manually")
            retry_raw_text = inference_client.complete(
                messages=messages,
                temperature=0.1,
                json_schema=None,
                stream=retry_stream,
                on_token=(None if stream_callback is None else lambda chunk: stream_callback("plain_text_retry", chunk)),
                on_event=(None if progress is None else lambda message: progress(f"[llm] {message}")),
            )
            retry_elapsed_ms = (time.perf_counter() - retry_started) * 1000.0
            _emit_progress(
                progress,
                f"Plain-text retry call finished in {retry_elapsed_ms:.1f} ms; received {len(retry_raw_text)} chars",
            )
            _emit_progress(progress, "Plain-text retry raw LLM output captured; printing before parse")
            _emit_raw_output(raw_output_callback, "plain_text_retry", retry_raw_text)
            extract_started = time.perf_counter()
            _emit_progress(progress, "Extracting JSON object from plain-text retry response")
            extracted_json = extract_json_object_text(retry_raw_text)
            extract_elapsed_ms = (time.perf_counter() - extract_started) * 1000.0
            _emit_progress(progress, f"JSON extraction finished in {extract_elapsed_ms:.1f} ms")
            validation_started = time.perf_counter()
            _emit_progress(progress, "Validating extracted JSON against ComponentSpecDraft")
            validated_payload = _parse_payload(extracted_json)
            validation_elapsed_ms = (time.perf_counter() - validation_started) * 1000.0
            _emit_progress(progress, f"Retry validation finished in {validation_elapsed_ms:.1f} ms")
        except (InferenceClientError, ValidationError, ValueError, json.JSONDecodeError, RuntimeError) as retry_error:
            _emit_progress(progress, f"Step1 failed after retry: {retry_error}")
            return state.with_updates(
                status="aborted",
                abort_reason="step1_parse_fail",
                prompt_versions=merged_prompt_versions,
                retry_counts=retry_counts,
                errors=_append_error(
                    state.errors,
                    f"Step1 parse failed after retry: {retry_error}",
                ),
            )

    _emit_progress(progress, "Step1 completed successfully")
    return state.with_updates(
        status="ready",
        abort_reason="",
        component_spec_draft=validated_payload,
        spec_draft=validated_payload,
        prompt_versions=merged_prompt_versions,
        retry_counts=retry_counts,
    )


__all__ = ["step1_node"]
