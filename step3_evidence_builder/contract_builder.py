from __future__ import annotations

import re
from typing import Any


BASELINE_ALLOWED_APIS: tuple[str, ...] = (
    "setState",
    "onStateChange",
    "changeState",
)

ALLOWED_TODO_CATEGORIES: tuple[str, ...] = (
    "backend_call",
    "auth",
    "data_fetch",
    "complex_validation",
)


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _extract_required_state_keys(state_schema: Any) -> list[str]:
    if isinstance(state_schema, dict):
        return sorted(str(key).strip() for key in state_schema.keys() if str(key).strip())
    if isinstance(state_schema, list):
        keys: list[str] = []
        for item in state_schema:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("key") or "").strip()
                if name:
                    keys.append(name)
            else:
                name = str(item).strip()
                if name:
                    keys.append(name)
        return sorted(_dedupe(keys))
    return []


def _extract_required_dom_selectors(dom_requirements: Any) -> list[str]:
    selectors: list[str] = []
    if isinstance(dom_requirements, list):
        for item in dom_requirements:
            if isinstance(item, dict):
                for key in ("selector_hint", "selector", "css_selector", "path"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        selectors.append(value)
                        break
            else:
                value = str(item).strip()
                if value:
                    selectors.append(value)
    return _dedupe(selectors)


def _extract_required_event_bindings(events: Any) -> list[str]:
    bindings: list[str] = []
    if not isinstance(events, list):
        return bindings
    for event in events:
        if not isinstance(event, dict):
            continue
        value = str(
            event.get("type")
            or event.get("trigger")
            or event.get("name")
            or ""
        ).strip()
        if value:
            bindings.append(value)
    return _dedupe(bindings)


def _extract_unresolved_markers(spec_final: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    for key in ("todo_markers", "uncertainties"):
        value = spec_final.get(key) or []
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item).strip()
            if text:
                markers.append(text)
    return _dedupe(markers)


def _has_async_need(spec_final: dict[str, Any]) -> bool:
    events = spec_final.get("events") or []
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and bool(event.get("async_required")):
                return True

    async_requirements = spec_final.get("async_requirements") or {}
    if isinstance(async_requirements, list):
        return bool(async_requirements)
    if isinstance(async_requirements, dict):
        return bool(async_requirements.get("has_async")) or bool(async_requirements.get("needs_queue"))
    return False


def _needs_public_acquisition(spec_final: dict[str, Any]) -> bool:
    for key in ("child_gadget_needs", "acquisition_needs"):
        items = spec_final.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for marker_key in (
                "allow_public_acquisition",
                "needs_public_acquisition",
                "public_name",
                "exposed_methods",
                "public_methods",
            ):
                marker_value = item.get(marker_key)
                if isinstance(marker_value, bool) and marker_value:
                    return True
                if isinstance(marker_value, str) and marker_value.strip():
                    return True
                if isinstance(marker_value, list) and any(str(x).strip() for x in marker_value):
                    return True
    return False


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


def infer_required_slots(spec_final: dict[str, Any]) -> list[str]:
    slots = ["state_init", "dom_template", "render_logic"]
    if spec_final.get("events"):
        slots.append("event_bindings")
    if spec_final.get("child_gadget_needs"):
        slots.append("child_gadgets")
    if spec_final.get("acquisition_needs"):
        slots.append("acquired_methods")
    return _dedupe(slots)


def infer_allowed_api_names(spec_final: dict[str, Any]) -> list[str]:
    allowed = list(BASELINE_ALLOWED_APIS)

    if spec_final.get("events"):
        allowed.append("onEvent")

    child_gadget_needs = spec_final.get("child_gadget_needs") or []
    if child_gadget_needs:
        allowed.extend(["declareGadget", "getDeclaredGadget", "ready", "declareMethod"])

    acquisition_needs = spec_final.get("acquisition_needs") or []
    if acquisition_needs:
        allowed.extend(["declareAcquiredMethod", "declareMethod"])
    if _needs_public_acquisition(spec_final):
        allowed.append("allowPublicAcquisition")

    if _has_async_need(spec_final):
        allowed.append("RSVP.Queue")

    return sorted(_dedupe(allowed))


def build_generation_contract(
    spec_final: dict[str, Any],
    constraints: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> dict[str, Any]:
    evidence = evidence_pack.get("items") or evidence_pack.get("evidence") or []
    allowed_api_names = infer_allowed_api_names(spec_final)
    recommended_pattern_ids: list[str] = []

    for item in evidence:
        doc_type = str(item.get("doc_type") or (item.get("metadata") or {}).get("doc_type") or "").strip()
        if doc_type == "pattern":
            pattern_id = str(item.get("id") or item.get("doc_id") or "").strip()
            if pattern_id:
                recommended_pattern_ids.append(pattern_id)

    required_slots = infer_required_slots(spec_final)
    required_dom_selectors = _extract_required_dom_selectors(spec_final.get("dom_requirements") or [])
    required_state_keys = _extract_required_state_keys(spec_final.get("state_schema") or {})
    required_event_bindings = _extract_required_event_bindings(spec_final.get("events") or [])
    unresolved_markers = _extract_unresolved_markers(spec_final)
    return {
        "allowed_api_names": allowed_api_names,
        "recommended_pattern_ids": _dedupe(recommended_pattern_ids),
        "forbidden_patterns": list(constraints.get("forbidden_patterns") or []),
        "required_slots": required_slots,
        "required_dom_selectors": required_dom_selectors,
        "required_state_keys": required_state_keys,
        "required_event_bindings": required_event_bindings,
        "allowed_todo_categories": list(ALLOWED_TODO_CATEGORIES),
        "fallback_policy": "emit_todo_marker",
        "evidence_token_budget": int(
            (evidence_pack.get("stats") or {}).get("total_content_tokens_est")
            or evidence_pack.get("total_content_tokens_est")
            or (evidence_pack.get("stats") or {}).get("total_tokens_est")
            or evidence_pack.get("total_content_tokens_est")
            or evidence_pack.get("total_tokens_est")
            or 0
        ),
        "must_use_change_state": True,
        "dom_updates_in_on_state_change": bool(constraints.get("dom_writes_only_in_onstatechange", True)),
        "avoid_global_dom_selectors": bool(constraints.get("must_not_use_global_dom", True)),
        "emit_todo_for_unresolved_areas": True,
        "unresolved_markers": unresolved_markers,
    }
