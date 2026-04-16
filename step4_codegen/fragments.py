from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

from inference_client import InferenceClient, InferenceClientError
from step4_codegen.evidence_filter import filter_evidence_for_fragment


LOGGER = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
FRAGMENT_TEMPERATURE = 0.2
FRAGMENT_MAX_TOKENS = 2048
EVENTS_TODO_PLACEHOLDER = """    .onEvent("click", function () {
      /* TODO: event handler generation failed */
      return this.changeState({});
    }, false, false)"""
RENDER_TODO_PLACEHOLDER = """var el = this.element;
/* TODO: render logic generation failed */"""


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def _load_prompt_with_hash(filename: str) -> tuple[str, str]:
    text = _load_prompt(filename)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def _render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _extract_fenced_code_block(text: str, language: str) -> str | None:
    pattern = rf"```{language}\s*(.*?)```"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _format_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _state_rows(spec: dict[str, Any]) -> list[tuple[str, str, str]]:
    state_schema = spec.get("state_schema") or {}
    if isinstance(state_schema, dict):
        return [(str(key), str(value), "") for key, value in state_schema.items()]

    rows: list[tuple[str, str, str]] = []
    for item in state_schema if isinstance(state_schema, list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("key")
        field_type = item.get("field_type") or item.get("type") or "unknown"
        description = item.get("description")
        if not isinstance(name, str) or not name.strip():
            continue
        rows.append((name.strip(), str(field_type), description.strip() if isinstance(description, str) else ""))
    return rows


def _state_keys_with_types(spec: dict[str, Any]) -> str:
    rows = _state_rows(spec)
    if not rows:
        return "- (none)"
    return "\n".join(f"- {name}: {field_type}" for name, field_type, _ in rows)


def _state_keys_with_descriptions(spec: dict[str, Any]) -> str:
    rows = _state_rows(spec)
    if not rows:
        return "State fields: (none)"
    formatted: list[str] = []
    for name, field_type, description in rows:
        item = f"{name} ({field_type})"
        if description:
            item += f": {description}"
        formatted.append(item)
    return "State fields: " + ", ".join(formatted)


def _format_dom_requirements(spec: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in spec.get("dom_requirements") or []:
        if isinstance(item, str) and item.strip():
            lines.append(f"- {item.strip()}")
        elif isinstance(item, dict):
            selector = item.get("selector") or item.get("css_selector") or item.get("path")
            if isinstance(selector, str) and selector.strip():
                lines.append(f"- {selector.strip()}")
    return "\n".join(lines) if lines else "- (none)"


def _extract_spec_for_dom(spec: dict[str, Any]) -> str:
    ui_plan = spec.get("ui_plan") or []
    return (
        "UI plan:\n"
        f"{_format_json(ui_plan)}\n\n"
        "Required DOM selectors:\n"
        f"{_format_dom_requirements(spec)}"
    )


def _extract_spec_for_events(spec: dict[str, Any]) -> str:
    events = spec.get("events") or []
    event_bits: list[str] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        trigger = item.get("type") or item.get("trigger") or item.get("name") or "unknown"
        selector = item.get("selector") or item.get("target") or ""
        prevent_default = item.get("prevent_default")
        fragment = str(trigger)
        if isinstance(selector, str) and selector.strip():
            fragment += f" on {selector.strip()}"
        if prevent_default is True:
            fragment += " (prevent_default=true)"
        event_bits.append(fragment)
    events_text = ", ".join(event_bits) if event_bits else "(none)"
    state_rows = _state_rows(spec)
    state_text = ", ".join(f"{name} ({field_type})" for name, field_type, _ in state_rows) if state_rows else "(none)"
    return f"Events: {events_text}\nState fields: {state_text}"


def _extract_spec_for_render(spec: dict[str, Any]) -> str:
    return _state_keys_with_descriptions(spec)


def _estimate_tokens(text: str) -> int:
    return len(text) // 3


def _log_fragment_prompt(fragment_name: str, system_prompt: str, user_prompt: str) -> None:
    prompt_text = f"{system_prompt}\n\n{user_prompt}"
    token_est = _estimate_tokens(prompt_text)
    LOGGER.info(
        "Fragment %s prompt: %s chars, ~%s tokens est",
        fragment_name,
        len(prompt_text),
        token_est,
    )
    if token_est > 3000:
        LOGGER.warning(
            "Fragment %s prompt exceeds target budget: ~%s tokens est",
            fragment_name,
            token_est,
        )


def _call_fragment_llm(
    llm_client: InferenceClient,
    *,
    system_prompt: str,
    user_prompt: str,
    language: str,
    retries: int = 1,
) -> str | None:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw_text = llm_client.complete(
                messages=messages,
                temperature=FRAGMENT_TEMPERATURE,
                max_tokens=FRAGMENT_MAX_TOKENS,
                json_schema=None,
                stream=False,
            )
            extracted = _extract_fenced_code_block(raw_text, language)
            if extracted:
                return extracted
            last_error = ValueError(f"No ```{language}``` code block found in fragment response.")
        except (InferenceClientError, ValueError) as exc:
            last_error = exc
        if attempt < retries:
            LOGGER.warning("Step4 fragment parse failed, retrying once: %s", last_error)
    if last_error is not None:
        LOGGER.warning("Step4 fragment generation failed: %s", last_error)
    return None


def load_step4_prompt_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for filename in (
        "step4b_dom_system.md",
        "step4b_dom_user.md",
        "step4c_events_system.md",
        "step4c_events_user.md",
        "step4d_render_system.md",
        "step4d_render_user.md",
    ):
        _, digest = _load_prompt_with_hash(filename)
        versions[filename] = digest
    return versions


def generate_fragment_dom(
    spec: dict[str, Any],
    contract: dict[str, Any],
    evidence: dict[str, Any],
    llm_client: InferenceClient,
) -> str | None:
    system_prompt = _load_prompt("step4b_dom_system.md")
    user_template = _load_prompt("step4b_dom_user.md")
    evidence_text = filter_evidence_for_fragment(
        list(evidence.get("items") or []),
        "dom",
    )
    user_prompt = _render_template(
        user_template,
        {
            "ui_plan_json": _extract_spec_for_dom(spec),
            "dom_requirements": _format_dom_requirements(spec),
            "evidence_layout_examples": evidence_text,
        },
    )
    _log_fragment_prompt("dom", system_prompt, user_prompt)
    return _call_fragment_llm(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        language="html",
        retries=1,
    )


def generate_fragment_events(
    spec: dict[str, Any],
    contract: dict[str, Any],
    evidence: dict[str, Any],
    bridge: dict[str, Any],
    llm_client: InferenceClient,
) -> str | None:
    del contract
    system_prompt = _load_prompt("step4c_events_system.md")
    user_template = _load_prompt("step4c_events_user.md")
    evidence_text = filter_evidence_for_fragment(
        list(evidence.get("items") or []),
        "events",
    )
    user_prompt = _render_template(
        user_template,
        {
            "state_keys_with_types": _extract_spec_for_events(spec),
            "events_json": _extract_spec_for_events(spec),
            "actual_classes": _format_json(bridge.get("actual_classes") or []),
            "dom_html": str(bridge.get("dom_html") or ""),
            "evidence_event_patterns": evidence_text,
        },
    )
    _log_fragment_prompt("events", system_prompt, user_prompt)
    return _call_fragment_llm(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        language="javascript",
        retries=1,
    )


def generate_fragment_render(
    spec: dict[str, Any],
    contract: dict[str, Any],
    evidence: dict[str, Any],
    bridge: dict[str, Any],
    llm_client: InferenceClient,
) -> str | None:
    del contract
    system_prompt = _load_prompt("step4d_render_system.md")
    user_template = _load_prompt("step4d_render_user.md")
    evidence_text = filter_evidence_for_fragment(
        list(evidence.get("items") or []),
        "render",
    )
    user_prompt = _render_template(
        user_template,
        {
            "state_keys_with_descriptions": _extract_spec_for_render(spec),
            "actual_classes": _format_json(bridge.get("actual_classes") or []),
            "dom_html": str(bridge.get("dom_html") or ""),
            "evidence_state_patterns": evidence_text,
        },
    )
    _log_fragment_prompt("render", system_prompt, user_prompt)
    return _call_fragment_llm(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        language="javascript",
        retries=1,
    )
