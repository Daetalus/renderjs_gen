from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from inference_client import InferenceClient, LlamaCppClient
from pipeline_state import PipelineState
from step4_codegen.assembler import assemble_gadget
from step4_codegen.deterministic import generate_acquired_methods, generate_state_init
from step4_codegen.fragment_bridge import build_fragment_bridge
from step4_codegen.fragments import (
    EVENTS_TODO_PLACEHOLDER,
    RENDER_TODO_PLACEHOLDER,
    generate_fragment_dom,
    generate_fragment_events,
    generate_fragment_render,
    load_step4_prompt_versions,
)


LOGGER = logging.getLogger(__name__)


def _append_warning(warnings: list[str], message: str) -> list[str]:
    return [*warnings, message]


def _append_error(errors: list[str], message: str) -> list[str]:
    return [*errors, message]


def _to_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "renderjs-gadget"


def _write_fragment(base_dir: Path, filename: str, payload: str | dict[str, Any]) -> str:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / filename
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")
    return str(path)


def _needs_declare_methods(spec: dict[str, Any]) -> bool:
    for item in spec.get("child_gadget_needs") or []:
        if isinstance(item, dict) and (item.get("public_name") or item.get("method_name")):
            return True
    return False


def step4_node(
    state: PipelineState,
    client: InferenceClient | None = None,
) -> PipelineState:
    spec = state.spec or {}
    contract = state.generation_contract or {}
    evidence = state.evidence_pack or {}
    if not spec:
        return state.with_updates(
            status="aborted",
            abort_reason="step4_missing_spec",
            errors=_append_error(state.errors, "Step4 requires component_spec_final in state.spec."),
        )

    llm_client = client or LlamaCppClient()
    merged_prompt_versions = {**state.prompt_versions, **load_step4_prompt_versions()}
    fragment_dir = Path(state.out_dir or ".") / "step4" / "fragments"
    artifacts = dict(state.artifacts)

    state_init = generate_state_init(spec)
    acquired_methods = generate_acquired_methods(spec)
    artifacts["step4.fragment_state_init"] = _write_fragment(fragment_dir, "state_init.js", state_init)
    if acquired_methods.strip():
        artifacts["step4.fragment_acquired_methods"] = _write_fragment(
            fragment_dir,
            "acquired_methods.js",
            acquired_methods,
        )

    dom_template = generate_fragment_dom(spec, contract, evidence, llm_client)
    if dom_template is None:
        return state.with_updates(
            status="aborted",
            abort_reason="step4b_dom_generation_failed",
            fragment_state_init=state_init,
            prompt_versions=merged_prompt_versions,
            artifacts=artifacts,
            errors=_append_error(state.errors, "Step4 DOM fragment generation failed after retry."),
        )
    artifacts["step4.fragment_dom"] = _write_fragment(fragment_dir, "dom.html", dom_template)

    bridge = build_fragment_bridge(dom_template, spec)
    artifacts["step4.fragment_bridge"] = _write_fragment(fragment_dir, "bridge.json", bridge)

    warnings = list(state.warnings)
    if bridge.get("missing_selectors"):
        warnings = _append_warning(
            warnings,
            f"Missing selectors in DOM fragment: {', '.join(bridge['missing_selectors'])}",
        )
        LOGGER.warning("Missing selectors in DOM fragment: %s", bridge["missing_selectors"])

    event_handlers = generate_fragment_events(spec, contract, evidence, bridge, llm_client)
    render_logic = generate_fragment_render(spec, contract, evidence, bridge, llm_client)

    next_status = state.status
    if next_status in {"ready", "running"}:
        next_status = "ready"

    if not event_handlers:
        event_handlers = EVENTS_TODO_PLACEHOLDER
        next_status = "degraded"
        warnings = _append_warning(warnings, "Step4 events fragment generation failed; TODO placeholder emitted.")
    if not render_logic:
        render_logic = RENDER_TODO_PLACEHOLDER
        next_status = "degraded"
        warnings = _append_warning(warnings, "Step4 render fragment generation failed; TODO placeholder emitted.")

    artifacts["step4.fragment_events"] = _write_fragment(fragment_dir, "events.js", event_handlers)
    artifacts["step4.fragment_render"] = _write_fragment(fragment_dir, "render.js", render_logic)

    declare_methods = ""
    if _needs_declare_methods(spec):
        declare_methods = "    /* TODO: declareMethod generation not implemented in POC */"
        artifacts["step4.fragment_methods"] = _write_fragment(fragment_dir, "methods.js", declare_methods)

    slug = _to_slug(str(spec.get("gadget_name") or spec.get("page_goal") or "renderjs-gadget"))
    title = str(spec.get("page_goal") or "RenderJS Gadget")
    html, js = assemble_gadget(
        slug=slug,
        title=title,
        state_init=state_init,
        acquired_methods=acquired_methods,
        dom_template=dom_template,
        event_handlers=event_handlers,
        render_logic=render_logic,
        declare_methods=declare_methods or None,
    )

    return state.with_updates(
        status=next_status,
        abort_reason="",
        fragment_state_init=state_init,
        fragment_dom=dom_template,
        fragment_bridge=bridge,
        fragment_events=event_handlers,
        fragment_render=render_logic,
        fragment_methods=declare_methods,
        code_html=html,
        code_js=js,
        prompt_versions=merged_prompt_versions,
        artifacts=artifacts,
        warnings=warnings,
    )


__all__ = ["step4_node"]
