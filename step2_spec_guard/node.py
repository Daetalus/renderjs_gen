from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any

from pipeline_state import PipelineState
from step2_spec_guard.rules import (
    COMPONENT_WHITELIST,
    FIELD_GROUP_APPLIES_TO,
    FIELD_GROUP_FORBIDDEN_PATTERNS,
    FIELD_GROUP_MAPPING,
    RENDERJS_CONSTRAINTS,
    RENDERJS_FORBIDDEN_PATTERNS,
)

FIELD_GROUP_ORDER: tuple[str, ...] = (
    "layout_html",
    "state_logic",
    "event_binding",
    "async_flow",
    "acquisition",
    "child_gadget",
    "error_boundary",
)

EVENT_TRIGGER_ALIASES: dict[str, str] = {
    "onclick": "click",
    "on_click": "click",
    "tap": "click",
    "onsubmit": "submit",
    "on_submit": "submit",
    "onchange": "change",
    "on_change": "change",
    "text_input": "input",
    "oninput": "input",
    "on_input": "input",
    "key_down": "keydown",
    "key_up": "keyup",
}

COMPONENT_ELEMENT_HINTS: dict[str, str] = {
    "page": "section",
    "panel": "section",
    "section": "section",
    "form": "form",
    "fieldset": "fieldset",
    "input": "input",
    "textarea": "textarea",
    "select": "select",
    "checkbox": "input",
    "radio": "input",
    "button": "button",
    "list": "ul",
    "list_item": "li",
    "table": "table",
    "card": "article",
    "banner": "section",
    "notice": "section",
    "dialog": "section",
    "toolbar": "nav",
    "tabs": "section",
    "pagination": "nav",
    "empty_state": "section",
    "loading_state": "section",
}

CONSTRAINT_COMPAT_RULES: dict[str, dict[str, Any]] = {
    "must_use_rsvp_queue": {
        "title": "Use RSVP.Queue for async chains",
        "summary": "Async flows must be expressed as RSVP.Queue chains and returned to RenderJS.",
        "official_api_names": ["RSVP.Queue"],
        "field_groups": ("async_flow",),
        "severity": "blocking",
    },
    "must_not_use_then": {
        "title": "Do not use raw Promise.then chains",
        "summary": "Avoid raw .then chains in generated gadgets.",
        "official_api_names": ["RSVP.Queue"],
        "field_groups": ("async_flow",),
        "severity": "blocking",
    },
    "must_not_call_external_changestate": {
        "title": "Only mutate state through gadget.changeState",
        "summary": "Do not call changeState on external gadgets or globals.",
        "official_api_names": ["changeState"],
        "field_groups": ("state_logic",),
        "severity": "blocking",
    },
    "dom_writes_only_in_onstatechange": {
        "title": "Keep DOM writes inside onStateChange",
        "summary": "RenderJS DOM mutation should happen in onStateChange.",
        "official_api_names": ["onStateChange"],
        "field_groups": ("layout_html", "state_logic"),
        "severity": "blocking",
    },
}


def _issue_id(category: str, path: str, message: str) -> str:
    digest = hashlib.sha1(f"{category}|{path}|{message}".encode("utf-8")).hexdigest()[:10]
    return f"{category}:{digest}"


def _make_issue(
    *,
    severity: str,
    category: str,
    path: str,
    message: str,
    repair_hint: str = "",
) -> dict[str, Any]:
    issue = {
        "issue_id": _issue_id(category, path, message),
        "severity": severity,
        "category": category,
        "path": path,
        "message": message,
    }
    if repair_hint:
        issue["repair_hint"] = repair_hint
    return issue


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _normalize_area_id(value: Any) -> str:
    token = _normalize_token(value)
    return token or "area"


def _selector_for_area(area_id: str) -> str:
    return f".{area_id.replace('_', '-')}"


def _normalize_trigger(value: Any) -> str:
    token = _normalize_token(value)
    if not token:
        return "custom"
    token = EVENT_TRIGGER_ALIASES.get(token, token)
    token = token.replace("_", "")
    if token in {"click", "submit", "change", "input", "keydown", "keyup", "blur", "focus"}:
        return token
    return token or "custom"


def _unique_event_name(base_name: str, seen: set[str]) -> str:
    if base_name not in seen:
        seen.add(base_name)
        return base_name
    index = 2
    while f"{base_name}_{index}" in seen:
        index += 1
    candidate = f"{base_name}_{index}"
    seen.add(candidate)
    return candidate


def _infer_state_field(name: str) -> dict[str, Any]:
    token = _normalize_token(name)
    if token.startswith(("is_", "has_", "can_", "should_")) or token in {
        "loading",
        "submitting",
        "disabled",
        "visible",
        "expanded",
        "selected",
    }:
        field_type = "boolean"
        default: Any = False
    elif token.endswith(("_list", "_items")) or token in {"items", "rows", "options"}:
        field_type = "array"
        default = []
    elif token.endswith(("_count", "_total", "_index")):
        field_type = "number"
        default = 0
    elif token.endswith("_data") or token.endswith("_map") or token.endswith("_object"):
        field_type = "object"
        default = {}
    else:
        field_type = "string"
        default = ""
    return {
        "name": token or "value",
        "field_type": field_type,
        "default": default,
        "required": False,
        "description": f"Auto-added state for Step2 guard: {token or 'value'}",
    }


def _append_state_field_if_missing(
    state_schema: list[dict[str, Any]],
    known_fields: set[str],
    field_name: str,
    issues: list[dict[str, Any]],
    *,
    reason: str,
) -> None:
    token = _normalize_token(field_name)
    if not token or token in known_fields:
        return
    state_schema.append(_infer_state_field(token))
    known_fields.add(token)
    issues.append(
        _make_issue(
            severity="warning",
            category="state_completion",
            path="state_schema",
            message=f"Auto-added missing state field '{token}' ({reason}).",
        )
    )


def _has_submit_event(spec: dict[str, Any]) -> bool:
    for event in spec.get("events") or []:
        if isinstance(event, dict) and _normalize_trigger(event.get("trigger")) == "submit":
            return True
    return False


def _infer_state_fields_from_todo_markers(spec: dict[str, Any]) -> list[str]:
    inferred: list[str] = []
    task_type = str(spec.get("task_type") or "").strip().lower()
    has_submit = _has_submit_event(spec)

    for marker in spec.get("todo_markers") or []:
        text = str(marker or "").strip().lower()
        if not text:
            continue
        if "error" in text:
            inferred.append("error_message")
        if "loading" in text or "submitting" in text:
            if task_type == "form" and has_submit:
                inferred.append("is_submitting")
            else:
                inferred.append("loading")
    return _dedupe_preserve_order(inferred)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _title_from_area_id(area_id: str) -> str:
    words = [part for part in area_id.replace("-", "_").split("_") if part]
    if not words:
        return "Area"
    return " ".join(word.capitalize() for word in words)


def _normalize_component_kind(value: Any) -> str:
    token = _normalize_token(value)
    return token if token in COMPONENT_WHITELIST else "section"


def _extract_state_fields(spec: dict[str, Any]) -> list[dict[str, Any]]:
    state_schema = spec.get("state_schema") or []
    if isinstance(state_schema, dict):
        return [
            {"name": str(name).strip(), "field_type": str(field_type).strip()}
            for name, field_type in state_schema.items()
            if str(name).strip()
        ]
    return [item for item in state_schema if isinstance(item, dict)]


def _dom_selector_map(spec: dict[str, Any]) -> dict[str, str]:
    selector_map: dict[str, str] = {}
    for item in spec.get("dom_requirements") or []:
        if not isinstance(item, dict):
            continue
        selector = str(item.get("selector_hint") or item.get("selector") or item.get("css_selector") or "").strip()
        if not selector.startswith("."):
            continue
        normalized = _normalize_token(selector.lstrip("."))
        if normalized and normalized not in selector_map:
            selector_map[normalized] = selector
    return selector_map


def _area_id_from_selector(selector: str, fallback: str) -> str:
    normalized = _normalize_token(str(selector).lstrip("."))
    return normalized or fallback


def _choose_selector(selector_map: dict[str, str], *candidates: str) -> str | None:
    for candidate in candidates:
        token = _normalize_token(candidate)
        if token and token in selector_map:
            return selector_map[token]
    return None


def _infer_element_tag(component_kind: str) -> str:
    mapping = {
        "form": "form",
        "input": "input",
        "textarea": "textarea",
        "select": "select",
        "button": "button",
        "list": "ul",
        "list_item": "li",
        "table": "table",
        "section": "section",
        "notice": "div",
        "card": "div",
        "panel": "div",
        "page": "div",
    }
    return mapping.get(component_kind, COMPONENT_ELEMENT_HINTS.get(component_kind, "div"))


def _append_ui_plan_item(items: list[dict[str, Any]], *, area_id: str, component_kind: str, purpose: str) -> None:
    normalized_area_id = _normalize_area_id(area_id)
    if any(str(item.get("area_id") or "") == normalized_area_id for item in items):
        return
    kind = _normalize_component_kind(component_kind)
    items.append(
        {
            "area_id": normalized_area_id,
            "title": _title_from_area_id(normalized_area_id),
            "component_kind": kind,
            "purpose": purpose.strip(),
        }
    )


def _default_form_area_id(spec: dict[str, Any], selector_map: dict[str, str]) -> str:
    selector = _choose_selector(selector_map, "login_form", "main_form", "form")
    if selector:
        return _area_id_from_selector(selector, "main_form")
    page_goal = str(spec.get("page_goal") or "").lower()
    if "login" in page_goal:
        return "login_form"
    for event in spec.get("events") or []:
        if not isinstance(event, dict):
            continue
        source_area_id = _normalize_area_id(event.get("source_area_id"))
        if source_area_id and source_area_id != "area":
            if source_area_id.endswith("_area"):
                return source_area_id[:-5] + "_form"
            return source_area_id
    return "main_form"


def _synthesize_form_ui_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    selector_map = _dom_selector_map(spec)
    items: list[dict[str, Any]] = []
    input_names: list[str] = []
    _append_ui_plan_item(
        items,
        area_id=_default_form_area_id(spec, selector_map),
        component_kind="form",
        purpose="Collect credentials",
    )

    for field in _extract_state_fields(spec):
        name = _normalize_token(field.get("name"))
        field_type = str(field.get("field_type") or field.get("type") or "").strip().lower()
        if not name:
            continue
        if field_type == "boolean" and ("loading" in name or "submitting" in name):
            continue
        if field_type == "string" and ("error" in name or "message" in name):
            selector = _choose_selector(selector_map, name, "error_msg", "error_message")
            area_id = _area_id_from_selector(selector or ".error-msg", "error_msg")
            _append_ui_plan_item(
                items,
                area_id=area_id,
                component_kind="notice",
                purpose=f"Display {name} state",
            )
            continue
        if field_type == "string" and "password" in name:
            selector = _choose_selector(selector_map, name, "password_input")
            area_id = _area_id_from_selector(selector or f".{name}-input", f"{name}_input")
            _append_ui_plan_item(
                items,
                area_id=area_id,
                component_kind="input",
                purpose=f"Password input for {name}",
            )
            input_names.append(name)
            continue
        if field_type == "string":
            selector = _choose_selector(selector_map, name, f"{name}_input")
            area_id = _area_id_from_selector(selector or f".{name}-input", f"{name}_input")
            _append_ui_plan_item(
                items,
                area_id=area_id,
                component_kind="input",
                purpose=f"Text input for {name}",
            )
            input_names.append(name)

    if _has_submit_event(spec):
        selector = _choose_selector(selector_map, "submit_btn", "submit_button")
        area_id = _area_id_from_selector(selector or ".submit-btn", "submit_btn")
        _append_ui_plan_item(
            items,
            area_id=area_id,
            component_kind="button",
            purpose="Submit the form",
        )

    has_error_feedback = any(
        "error" in _normalize_token(field.get("name")) or "message" in _normalize_token(field.get("name"))
        for field in _extract_state_fields(spec)
    ) or any(
        "error" in str(marker).lower() or "message" in str(marker).lower()
        for marker in (spec.get("todo_markers") or [])
    )
    if has_error_feedback:
        selector = _choose_selector(selector_map, "error_msg", "error_message")
        area_id = _area_id_from_selector(selector or ".error-msg", "error_msg")
        _append_ui_plan_item(
            items,
            area_id=area_id,
            component_kind="notice",
            purpose="Display error feedback",
        )

    if input_names:
        items[0]["purpose"] = f"Collect {' and '.join(input_names)}"

    return items


def _synthesize_display_like_ui_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    selector_map = _dom_selector_map(spec)
    items: list[dict[str, Any]] = []
    _append_ui_plan_item(
        items,
        area_id="main_section",
        component_kind="section",
        purpose="Main content container",
    )
    for field in _extract_state_fields(spec):
        name = _normalize_token(field.get("name"))
        field_type = str(field.get("field_type") or field.get("type") or "").strip().lower()
        if not name:
            continue
        selector = _choose_selector(selector_map, name)
        area_id = _area_id_from_selector(selector or f".{name}", name)
        component_kind = "section" if field_type == "object" else "text"
        if component_kind == "text":
            component_kind = "section"
        purpose = f"Display {name} value"
        _append_ui_plan_item(items, area_id=area_id, component_kind=component_kind, purpose=purpose)
    return items


def _synthesize_list_ui_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    selector_map = _dom_selector_map(spec)
    items: list[dict[str, Any]] = []
    _append_ui_plan_item(
        items,
        area_id="main_list",
        component_kind="list",
        purpose="Primary list container",
    )
    for field in _extract_state_fields(spec):
        name = _normalize_token(field.get("name"))
        field_type = str(field.get("field_type") or field.get("type") or "").strip().lower()
        if not name:
            continue
        if field_type == "array":
            selector = _choose_selector(selector_map, name, f"{name}_list")
            area_id = _area_id_from_selector(selector or f".{name}-list", f"{name}_list")
            _append_ui_plan_item(
                items,
                area_id=area_id,
                component_kind="list",
                purpose=f"Render items from {name}",
            )
        elif field_type == "boolean" and ("empty" in name or name.startswith("has_")):
            selector = _choose_selector(selector_map, name, "empty_state")
            area_id = _area_id_from_selector(selector or f".{name}", name)
            _append_ui_plan_item(
                items,
                area_id=area_id,
                component_kind="empty_state",
                purpose=f"Display empty-state feedback for {name}",
            )
    return items


def synthesize_ui_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    task_type = str(spec.get("task_type") or "").strip().lower()
    if task_type == "form":
        return _synthesize_form_ui_plan(spec)
    if task_type == "list":
        return _synthesize_list_ui_plan(spec)
    return _synthesize_display_like_ui_plan(spec)


def _sync_dom_requirements(spec: dict[str, Any]) -> None:
    dom_requirements = [item for item in (spec.get("dom_requirements") or []) if isinstance(item, dict)]
    existing_selectors = {
        str(item.get("selector_hint") or "").strip()
        for item in dom_requirements
        if str(item.get("selector_hint") or "").strip()
    }
    for item in spec.get("ui_plan") or []:
        if not isinstance(item, dict):
            continue
        area_id = _normalize_area_id(item.get("area_id"))
        selector = _selector_for_area(area_id)
        if selector in existing_selectors:
            continue
        dom_requirements.append(
            {
                "selector_hint": selector,
                "element": _infer_element_tag(str(item.get("component_kind") or "")),
                "purpose": str(item.get("purpose") or "").strip(),
                "required": True,
            }
        )
        existing_selectors.add(selector)
    spec["dom_requirements"] = dom_requirements


def _clip_ui_plan(spec: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    filtered_ui_plan: list[dict[str, Any]] = []
    removed_kinds: list[str] = []
    for index, item in enumerate(spec.get("ui_plan") or []):
        if not isinstance(item, dict):
            continue
        component_kind = _normalize_token(item.get("component_kind"))
        if component_kind in COMPONENT_WHITELIST:
            normalized = dict(item)
            normalized["component_kind"] = component_kind
            normalized["area_id"] = _normalize_area_id(item.get("area_id"))
            filtered_ui_plan.append(normalized)
            continue
        removed_kinds.append(component_kind or str(item.get("component_kind") or "unknown"))
        issues.append(
            _make_issue(
                severity="warning",
                category="whitelist_pruning",
                path=f"ui_plan[{index}].component_kind",
                message=f"Removed unsupported component_kind '{item.get('component_kind', '')}' from ui_plan.",
                repair_hint="Use a component from the RenderJS POC whitelist.",
            )
        )
    spec["ui_plan"] = filtered_ui_plan
    whitelist_used = [
        _normalize_token(item) for item in (spec.get("component_whitelist_used") or []) if _normalize_token(item)
    ]
    whitelist_used.extend(item.get("component_kind", "") for item in filtered_ui_plan)
    spec["component_whitelist_used"] = _dedupe_preserve_order(
        [item for item in whitelist_used if item in COMPONENT_WHITELIST]
    )
    if removed_kinds and not spec["ui_plan"]:
        issues.append(
            _make_issue(
                severity="error",
                category="whitelist_pruning",
                path="ui_plan",
                message="All ui_plan items were removed by the component whitelist.",
                repair_hint="Reduce the draft to supported POC components.",
            )
        )


def _ensure_state_schema(spec: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    state_schema = [item for item in (spec.get("state_schema") or []) if isinstance(item, dict)]
    known_fields = {_normalize_token(item.get("name")) for item in state_schema}

    for event in spec.get("events") or []:
        if not isinstance(event, dict):
            continue
        for field_name in event.get("updates_state") or []:
            _append_state_field_if_missing(
                state_schema,
                known_fields,
                str(field_name),
                issues,
                reason="referenced by event updates_state",
            )

    for requirement in spec.get("async_requirements") or []:
        if not isinstance(requirement, dict):
            continue
        for key in ("success_state", "error_state"):
            raw_value = str(requirement.get(key) or "").strip()
            if not raw_value:
                continue
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_value):
                _append_state_field_if_missing(
                    state_schema,
                    known_fields,
                    token,
                    issues,
                    reason=f"referenced by async_requirements.{key}",
                )

    for field_name in _infer_state_fields_from_todo_markers(spec):
        _append_state_field_if_missing(
            state_schema,
            known_fields,
            field_name,
            issues,
            reason="suggested by todo_markers",
        )

    if str(spec.get("task_type") or "").strip().lower() == "form" and _has_submit_event(spec):
        loading_like_fields = {"is_submitting", "loading", "is_loading", "submitting"}
        if not (known_fields & loading_like_fields):
            _append_state_field_if_missing(
                state_schema,
                known_fields,
                "is_submitting",
                issues,
                reason="required for form submit flow",
            )
        if "error_message" not in known_fields:
            _append_state_field_if_missing(
                state_schema,
                known_fields,
                "error_message",
                issues,
                reason="required for form error feedback",
            )

    spec["state_schema"] = state_schema


def _add_dom_requirement(
    dom_requirements: list[dict[str, Any]],
    known_selectors: set[str],
    selector: str,
    *,
    element: str,
    purpose: str,
    issues: list[dict[str, Any]],
    reason: str,
) -> None:
    normalized_selector = str(selector or "").strip()
    if not normalized_selector or normalized_selector in known_selectors:
        return
    dom_requirements.append(
        {
            "selector_hint": normalized_selector,
            "element": element,
            "purpose": purpose,
            "required": True,
        }
    )
    known_selectors.add(normalized_selector)
    issues.append(
        _make_issue(
            severity="warning",
            category="dom_completion",
            path="dom_requirements",
            message=f"Auto-added DOM requirement '{normalized_selector}' ({reason}).",
        )
    )


def _infer_dom_requirements_from_spec(
    spec: dict[str, Any],
    dom_requirements: list[dict[str, Any]],
    known_selectors: set[str],
    issues: list[dict[str, Any]],
) -> None:
    task_type = str(spec.get("task_type") or "").strip().lower()
    has_submit = _has_submit_event(spec)

    for event in spec.get("events") or []:
        if not isinstance(event, dict):
            continue
        source_area_id = _normalize_area_id(event.get("source_area_id"))
        if source_area_id and source_area_id != "area":
            _add_dom_requirement(
                dom_requirements,
                known_selectors,
                _selector_for_area(source_area_id),
                element="section",
                purpose=f"Primary area for event source '{source_area_id}'",
                issues=issues,
                reason="derived from event source_area_id",
            )

    state_names = {
        _normalize_token(item.get("name"))
        for item in (spec.get("state_schema") or [])
        if isinstance(item, dict)
    }

    if task_type == "form" or has_submit:
        _add_dom_requirement(
            dom_requirements,
            known_selectors,
            ".login-form",
            element="form",
            purpose="Primary form container",
            issues=issues,
            reason="required for form submit flow",
        )
        _add_dom_requirement(
            dom_requirements,
            known_selectors,
            ".submit-btn",
            element="button",
            purpose="Primary submit action",
            issues=issues,
            reason="required for form submit flow",
        )

    for state_name in sorted(state_names):
        if state_name in {"username", "email", "login"}:
            _add_dom_requirement(
                dom_requirements,
                known_selectors,
                f".{state_name.replace('_', '-')}-input",
                element="input",
                purpose=f"Input control for {state_name}",
                issues=issues,
                reason="derived from form state field",
            )
        elif state_name == "password":
            _add_dom_requirement(
                dom_requirements,
                known_selectors,
                ".password-input",
                element="input",
                purpose="Password input control",
                issues=issues,
                reason="derived from password state field",
            )
        elif state_name in {"error", "error_message"}:
            _add_dom_requirement(
                dom_requirements,
                known_selectors,
                ".error-message",
                element="div",
                purpose="Inline error feedback",
                issues=issues,
                reason="derived from error state field",
            )


def _ensure_dom_requirements(spec: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    dom_requirements = [item for item in (spec.get("dom_requirements") or []) if isinstance(item, dict)]
    known_selectors = {
        str(item.get("selector_hint") or "").strip()
        for item in dom_requirements
        if str(item.get("selector_hint") or "").strip()
    }
    for item in spec.get("ui_plan") or []:
        if not isinstance(item, dict):
            continue
        area_id = _normalize_area_id(item.get("area_id"))
        selector = _selector_for_area(area_id)
        if selector in known_selectors:
            continue
        _add_dom_requirement(
            dom_requirements,
            known_selectors,
            selector,
            element=COMPONENT_ELEMENT_HINTS.get(_normalize_token(item.get("component_kind")), "section"),
            purpose=str(item.get("purpose") or item.get("title") or "").strip(),
            issues=issues,
            reason=f"derived from ui_plan area '{area_id}'",
        )
    _infer_dom_requirements_from_spec(spec, dom_requirements, known_selectors, issues)
    spec["dom_requirements"] = dom_requirements


def _normalize_events(spec: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    normalized_events: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, event in enumerate(spec.get("events") or []):
        if not isinstance(event, dict):
            continue
        normalized = dict(event)
        trigger = _normalize_trigger(event.get("trigger"))
        source_area_id = _normalize_area_id(event.get("source_area_id"))
        updates_state = _dedupe_preserve_order([_normalize_token(item) for item in (event.get("updates_state") or [])])
        base_name = f"on_{trigger}"
        if source_area_id and source_area_id != "area":
            base_name = f"{base_name}_{source_area_id}"
        name = _unique_event_name(base_name, seen_names)

        if (
            str(event.get("name") or "") != name
            or str(event.get("trigger") or "") != trigger
            or str(event.get("source_area_id") or "") != source_area_id
        ):
            issues.append(
                _make_issue(
                    severity="warning",
                    category="event_normalization",
                    path=f"events[{index}]",
                    message=f"Normalized event '{event.get('name', '') or 'unnamed_event'}' to '{name}'.",
                )
            )

        normalized["name"] = name
        normalized["trigger"] = trigger
        normalized["source_area_id"] = source_area_id if source_area_id != "area" else ""
        normalized["updates_state"] = updates_state
        normalized["async_required"] = bool(event.get("async_required", False))
        normalized_events.append(normalized)
    spec["events"] = normalized_events


def _activate_field_groups(spec: dict[str, Any]) -> list[str]:
    active: set[str] = set()
    for field_name, groups in FIELD_GROUP_MAPPING.items():
        value = spec.get(field_name)
        if value in (None, "", [], {}):
            continue
        active.update(groups)
    if spec.get("ui_plan") or spec.get("dom_requirements"):
        active.add("layout_html")
    if spec.get("state_schema") or spec.get("events"):
        active.add("state_logic")
    return [group for group in FIELD_GROUP_ORDER if group in active]


def _build_compat_rules(active_field_groups: list[str], forbidden_patterns: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canon_rules: list[dict[str, Any]] = []
    for rule_key, meta in CONSTRAINT_COMPAT_RULES.items():
        groups = [group for group in meta["field_groups"] if group in active_field_groups]
        if not groups:
            continue
        applies_to: list[str] = []
        for group in groups:
            applies_to.extend(FIELD_GROUP_APPLIES_TO.get(group, (group,)))
        canon_rules.append(
            {
                "rule_id": rule_key,
                "title": meta["title"],
                "summary": meta["summary"],
                "severity": meta["severity"],
                "applies_to": _dedupe_preserve_order(applies_to),
                "official_api_names": list(meta["official_api_names"]),
            }
        )

    local_rules = [
        {
            "rule_id": f"forbidden_pattern_{index + 1}",
            "title": f"Forbidden code pattern: {pattern}",
            "summary": f"Generated code must not contain `{pattern}`.",
            "severity": "blocking",
            "applies_to": _dedupe_preserve_order(
                applies_to
                for group in active_field_groups
                for applies_to in FIELD_GROUP_APPLIES_TO.get(group, (group,))
            ),
            "official_api_names": [],
            "forbidden_pattern": pattern,
        }
        for index, pattern in enumerate(forbidden_patterns)
    ]
    return canon_rules, local_rules


def _build_constraints_bundle(spec: dict[str, Any]) -> dict[str, Any]:
    active_field_groups = _activate_field_groups(spec)
    forbidden_patterns = _dedupe_preserve_order(
        list(RENDERJS_FORBIDDEN_PATTERNS)
        + [
            pattern
            for group in active_field_groups
            for pattern in FIELD_GROUP_FORBIDDEN_PATTERNS.get(group, ())
        ]
    )
    canon_rules, local_rules = _build_compat_rules(active_field_groups, forbidden_patterns)
    bundle: dict[str, Any] = dict(RENDERJS_CONSTRAINTS)
    bundle["field_groups_activated"] = active_field_groups
    bundle["forbidden_patterns"] = forbidden_patterns
    bundle["canon_rules"] = canon_rules
    bundle["local_rules"] = local_rules
    return bundle


def _load_input_spec(state: PipelineState) -> dict[str, Any] | None:
    for candidate in (state.component_spec_draft, state.spec_draft, state.spec):
        if isinstance(candidate, dict) and candidate:
            return deepcopy(candidate)
    return None


def step2_node(state: PipelineState) -> PipelineState:
    spec = _load_input_spec(state)
    if spec is None:
        error = "Step2 requires component_spec_draft/spec_draft/spec in PipelineState."
        return state.with_updates(status="aborted", abort_reason="step2_missing_input", errors=[*state.errors, error])

    issues: list[dict[str, Any]] = []
    if not spec.get("ui_plan"):
        synthesized = synthesize_ui_plan(spec)
        spec["ui_plan"] = synthesized
        info_issue = _make_issue(
            severity="info",
            category="ui_plan_synthesized",
            path="ui_plan",
            message="ui_plan was empty, synthesized from state_schema and events.",
        )
        info_issue["synthesized_count"] = len(synthesized)
        issues.append(info_issue)
    _sync_dom_requirements(spec)
    _clip_ui_plan(spec, issues)
    _normalize_events(spec, issues)
    _ensure_state_schema(spec, issues)
    _ensure_dom_requirements(spec, issues)
    constraints_bundle = _build_constraints_bundle(spec)

    return state.with_updates(
        spec=spec,
        constraints=constraints_bundle,
        issues=issues,
        unresolved_issues=list(issues),
    )


__all__ = ["step2_node"]
