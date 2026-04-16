from __future__ import annotations

from pipeline_state import PipelineState
from step2_spec_guard.graph import run_step2_guard
from step2_spec_guard.node import step2_node


VALID_DRAFT = {
    "task_type": "form",
    "page_goal": "Create a login form.",
    "assumptions": [],
    "uncertainties": ["Authentication endpoint details are not yet confirmed."],
    "degradation_policy": {"mode": "conservative", "summary": "Keep the form usable without advanced recovery flows."},
    "ui_plan": [
        {
            "area_id": "login_form",
            "title": "Login Form",
            "component_kind": "form",
            "purpose": "Collect username and password",
        },
        {
            "area_id": "submit_button",
            "title": "Submit Button",
            "component_kind": "button",
            "purpose": "Submit credentials",
        },
        {
            "area_id": "hero_chart",
            "title": "Hero Chart",
            "component_kind": "chart",
            "purpose": "Unsupported visualization",
        },
    ],
    "component_whitelist_used": ["form", "button", "chart"],
    "state_schema": [
        {
            "name": "username",
            "field_type": "string",
            "default": "",
            "required": True,
            "description": "Username input",
        }
    ],
    "events": [
        {
            "name": "Submit Login",
            "trigger": "onSubmit",
            "source_area_id": "login_form",
            "handler_goal": "Submit the login form",
            "updates_state": ["is_loading", "error_message"],
            "async_required": True,
        }
    ],
    "dom_requirements": [
        {
            "selector_hint": ".login-form",
            "element": "form",
            "purpose": "Wrap the login inputs",
            "required": True,
        }
    ],
    "data_requirements": [],
    "async_requirements": [
        {
            "name": "submit_login",
            "trigger": "submit",
            "success_state": "save_status",
            "error_state": "error_message",
            "fallback": "Keep the form visible and show an inline error.",
        }
    ],
    "child_gadget_needs": [],
    "acquisition_needs": [],
    "allowed_degradation": [],
    "todo_markers": ["Confirm the exact authentication error payload."],
}


SPARSE_LOGIN_DRAFT = {
    "task_type": "form",
    "page_goal": "A minimal login form with username, password, and a submit button.",
    "assumptions": [],
    "uncertainties": [],
    "degradation_policy": {"mode": "conservative", "summary": ""},
    "ui_plan": [],
    "component_whitelist_used": [],
    "state_schema": [
        {
            "name": "username",
            "field_type": "string",
            "default": "",
            "required": False,
            "description": "The user's input for username",
        },
        {
            "name": "password",
            "field_type": "string",
            "default": "",
            "required": False,
            "description": "The user's input for password",
        },
    ],
    "events": [
        {
            "name": "submit_login",
            "trigger": "submit",
            "source_area_id": "login_area",
            "handler_goal": "Submit credentials",
            "updates_state": [],
            "async_required": False,
        }
    ],
    "dom_requirements": [],
    "data_requirements": [],
    "async_requirements": [],
    "child_gadget_needs": [],
    "acquisition_needs": [],
    "allowed_degradation": [],
    "todo_markers": [
        "Add error message state",
        "Add loading state",
        "Add 'remember me' checkbox",
    ],
}


def test_step2_node_normalizes_spec_and_builds_constraints() -> None:
    result = step2_node(PipelineState(component_spec_draft=VALID_DRAFT))

    assert result.status == "ready"
    assert result.abort_reason == ""
    assert result.spec is not None
    assert result.constraints is not None

    ui_plan = result.spec["ui_plan"]
    assert [item["component_kind"] for item in ui_plan] == ["form", "button"]
    assert result.spec["component_whitelist_used"] == ["form", "button"]

    state_names = {item["name"] for item in result.spec["state_schema"]}
    assert {"username", "is_loading", "error_message", "save_status"} <= state_names

    selectors = {item["selector_hint"] for item in result.spec["dom_requirements"]}
    assert ".login-form" in selectors
    assert ".submit-button" in selectors

    event = result.spec["events"][0]
    assert event["name"] == "on_submit_login_form"
    assert event["trigger"] == "submit"
    assert event["source_area_id"] == "login_form"

    constraints = result.constraints
    assert constraints["must_use_rsvp_queue"] is True
    assert constraints["must_not_use_global_dom"] is True
    assert constraints["field_groups_activated"] == [
        "layout_html",
        "state_logic",
        "event_binding",
        "async_flow",
        "error_boundary",
    ]
    assert ".then(" in constraints["forbidden_patterns"]
    assert ".addEventListener(" in constraints["forbidden_patterns"]
    assert "canon_rules" in constraints
    assert "local_rules" in constraints

    categories = {issue["category"] for issue in result.issues}
    assert "whitelist_pruning" in categories
    assert "event_normalization" in categories
    assert "state_completion" in categories
    assert "dom_completion" in categories
    assert result.unresolved_issues == result.issues


def test_run_step2_guard_remains_compatible_for_existing_callers() -> None:
    state = run_step2_guard({"spec": VALID_DRAFT, "max_rounds": 3})

    assert "spec" in state
    assert "constraints" in state
    assert "issues" in state
    assert state["final_ready"] is True
    assert state["termination_reason"] == "validated"
    assert state["validation_summary"]["warning_count"] >= 1
    assert ".then(" in state["constraints"]["forbidden_patterns"]
    assert state["spec"]["events"][0]["name"] == "on_submit_login_form"


def test_step2_node_backfills_sparse_login_draft_with_state_and_dom_requirements() -> None:
    result = step2_node(PipelineState(component_spec_draft=SPARSE_LOGIN_DRAFT))

    assert result.spec["ui_plan"]
    assert [item["component_kind"] for item in result.spec["ui_plan"]] == [
        "form",
        "input",
        "input",
        "button",
        "notice",
    ]
    assert [item["area_id"] for item in result.spec["ui_plan"]] == [
        "login_form",
        "username_input",
        "password_input",
        "submit_btn",
        "error_msg",
    ]

    state_names = {item["name"] for item in result.spec["state_schema"]}
    assert {"username", "password", "is_submitting", "error_message"} <= state_names

    selectors = {item["selector_hint"] for item in result.spec["dom_requirements"]}
    assert {
        ".login-area",
        ".login-form",
        ".username-input",
        ".password-input",
        ".submit-btn",
        ".error-message",
    } <= selectors

    synthesized_issues = [issue for issue in result.issues if issue["category"] == "ui_plan_synthesized"]
    assert len(synthesized_issues) == 1
    assert synthesized_issues[0]["synthesized_count"] == 5


def test_step2_node_does_not_override_existing_ui_plan() -> None:
    result = step2_node(PipelineState(component_spec_draft=VALID_DRAFT))

    area_ids = [item["area_id"] for item in result.spec["ui_plan"]]
    assert area_ids == ["login_form", "submit_button"]
    assert not any(issue["category"] == "ui_plan_synthesized" for issue in result.issues)
