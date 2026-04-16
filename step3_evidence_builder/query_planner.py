from __future__ import annotations

from typing import Any


DEFAULT_QUERY_LIMITS: dict[str, int] = {
    "rules": 5,
    "api": 5,
    "pattern": 3,
    "example": 2,
    "glossary": 2,
}


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


def infer_api_needs(spec_final: dict[str, Any]) -> list[str]:
    api_names = ["rJS(window)", "setState", "changeState", "onStateChange"]

    events = spec_final.get("events") or []
    if events:
        api_names.append("onEvent")

    async_requirements = spec_final.get("async_requirements") or {}
    if bool(async_requirements.get("has_async")) or bool(async_requirements.get("needs_queue")):
        api_names.extend(["RSVP.Queue", "declareMethod"])

    if spec_final.get("child_gadget_needs"):
        api_names.extend(["declareGadget", "getDeclaredGadget"])

    if spec_final.get("acquisition_needs"):
        api_names.extend(["declareAcquiredMethod", "allowPublicAcquisition"])

    return _dedupe(api_names)


def build_query_plan(spec_final: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    field_groups = [
        str(item).strip()
        for item in (constraints.get("field_groups_activated") or [])
        if str(item).strip()
    ]
    task_type = str(spec_final.get("task_type") or "display").strip() or "display"
    api_hints = infer_api_needs(spec_final)
    queries: list[dict[str, Any]] = []

    if field_groups:
        queries.append(
            {
                "intent": "rules",
                "query_text": f"RenderJS rules for {' '.join(field_groups)}",
                "filter": {"doc_type": "rule"},
                "n_results": DEFAULT_QUERY_LIMITS["rules"],
            }
        )

    if api_hints:
        queries.append(
            {
                "intent": "api",
                "query_text": f"RenderJS API {' '.join(api_hints)}",
                "filter": {"doc_type": "api"},
                "n_results": DEFAULT_QUERY_LIMITS["api"],
            }
        )

    if spec_final.get("events"):
        queries.append(
            {
                "intent": "event_pattern",
                "query_text": f"RenderJS event handling pattern {task_type}",
                "filter": {"doc_type": "pattern"},
                "n_results": DEFAULT_QUERY_LIMITS["pattern"],
            }
        )

    async_requirements = spec_final.get("async_requirements") or {}
    if bool(async_requirements.get("has_async")) or bool(async_requirements.get("needs_queue")):
        queries.append(
            {
                "intent": "async_pattern",
                "query_text": f"RenderJS RSVP.Queue async pattern {task_type}",
                "filter": {"doc_type": "pattern"},
                "n_results": DEFAULT_QUERY_LIMITS["pattern"],
            }
        )

    if spec_final.get("child_gadget_needs"):
        queries.append(
            {
                "intent": "child_gadget_pattern",
                "query_text": "RenderJS child gadget creation pattern",
                "filter": {"doc_type": "pattern"},
                "n_results": DEFAULT_QUERY_LIMITS["pattern"],
            }
        )
        queries.append(
            {
                "intent": "child_gadget_glossary",
                "query_text": "RenderJS child gadget scope sandbox glossary",
                "filter": {"doc_type": "glossary"},
                "n_results": DEFAULT_QUERY_LIMITS["glossary"],
            }
        )

    if spec_final.get("acquisition_needs"):
        queries.append(
            {
                "intent": "acquisition_pattern",
                "query_text": "RenderJS acquisition bridge pattern",
                "filter": {"doc_type": "pattern"},
                "n_results": DEFAULT_QUERY_LIMITS["pattern"],
            }
        )
        queries.append(
            {
                "intent": "acquisition_glossary",
                "query_text": "RenderJS acquisition glossary json compatible arguments",
                "filter": {"doc_type": "glossary"},
                "n_results": DEFAULT_QUERY_LIMITS["glossary"],
            }
        )

    queries.append(
        {
            "intent": "example",
            "query_text": f"RenderJS {task_type} example",
            "filter": {"doc_type": "example"},
            "n_results": DEFAULT_QUERY_LIMITS["example"],
        }
    )

    return {
        "field_groups_activated": field_groups,
        "api_hints": api_hints,
        "queries": queries,
    }
