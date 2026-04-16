from __future__ import annotations

RENDERJS_FORBIDDEN_PATTERNS: list[str] = [
    ".then(",
    "id=",
    "document.querySelector",
    "document.querySelectorAll",
    "document.getElementById",
    "document.body",
    "window.X =",
]

RENDERJS_CONSTRAINTS: dict[str, bool | str] = {
    "must_use_rsvp_queue": True,
    "must_not_use_then": True,
    "must_not_use_id_attr": True,
    "must_not_use_global_dom": True,
    "must_not_call_external_changestate": True,
    "must_not_use_global_vars": True,
    "must_return_promise_chains": True,
    "must_use_json_compatible_args": True,
    "dom_writes_only_in_onstatechange": True,
    "component_scope": "single_gadget",
    "event_naming": "normalized_snake_case",
}

COMPONENT_WHITELIST: set[str] = {
    "page",
    "panel",
    "section",
    "form",
    "fieldset",
    "input",
    "textarea",
    "select",
    "checkbox",
    "radio",
    "button",
    "list",
    "list_item",
    "table",
    "card",
    "banner",
    "notice",
    "dialog",
    "toolbar",
    "tabs",
    "pagination",
    "empty_state",
    "loading_state",
}

FIELD_GROUP_MAPPING: dict[str, tuple[str, ...]] = {
    "ui_plan": ("layout_html",),
    "dom_requirements": ("layout_html",),
    "state_schema": ("state_logic",),
    "events": ("event_binding", "state_logic"),
    "async_requirements": ("async_flow", "state_logic"),
    "data_requirements": ("async_flow",),
    "acquisition_needs": ("acquisition",),
    "child_gadget_needs": ("child_gadget",),
    "allowed_degradation": ("error_boundary",),
    "uncertainties": ("error_boundary",),
    "todo_markers": ("error_boundary",),
}

FIELD_GROUP_FORBIDDEN_PATTERNS: dict[str, tuple[str, ...]] = {
    "layout_html": ("innerHTML =", "outerHTML ="),
    "state_logic": ("this.state =", "state = state ||"),
    "event_binding": (".addEventListener(", "onclick ="),
    "async_flow": ("async function", "await "),
    "acquisition": ("window.parent",),
    "child_gadget": ("iframe.contentWindow",),
    "error_boundary": ("throw new Error(",),
}

FIELD_GROUP_APPLIES_TO: dict[str, tuple[str, ...]] = {
    "layout_html": ("ui_areas", "layout_html"),
    "state_logic": ("state_logic", "spec.state"),
    "event_binding": ("event_binding",),
    "async_flow": ("async_flow", "hints"),
    "acquisition": ("interfaces", "acquisition"),
    "child_gadget": ("child_gadgets", "child_gadget"),
    "error_boundary": ("error_boundary",),
}

