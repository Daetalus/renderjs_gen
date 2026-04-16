from __future__ import annotations

from step4_codegen.evidence_filter import filter_evidence_for_fragment


def _items() -> list[dict]:
    return [
        {
            "id": "rules_api_003",
            "doc_type": "rule",
            "field_groups": ["state_logic", "event_binding"],
            "content": "## Rule: DOM ownership + state-driven updates\n\nA gadget must not modify the global document DOM.\nIt must only manage its own gadget.element subtree.\nAll DOM writes MUST happen in onStateChange.",
        },
        {
            "id": "patterns_003",
            "doc_type": "pattern",
            "field_groups": ["event_binding", "async_flow"],
            "content": "## Pattern: form submit with prevent_default\n\n.onEvent(\"submit\", handler, false, true)\nHandler should changeState to \"loading\" first.",
        },
        {
            "id": "patterns_001",
            "doc_type": "pattern",
            "field_groups": ["state_logic", "event_binding"],
            "content": "## Pattern: state-driven rendering skeleton\n\nKeep DOM writes in onStateChange; event handlers only call changeState.",
        },
        {
            "id": "code_examples_003",
            "doc_type": "example",
            "field_groups": ["event_binding", "async_flow"],
            "content": "## Example: RSVP.Queue chain in submit handler\n\n.onEvent(\"submit\", function () {\n  return new RSVP.Queue()\n    .push(function () { return gadget.changeState({loading: true}); });\n})",
        },
        {
            "id": "code_examples_004",
            "doc_type": "example",
            "field_groups": ["layout_html"],
            "content": "## Example: minimal root gadget HTML\n\n<div class=\"root\">\n  <form class=\"login-form\"></form>\n</div>",
        },
        {
            "id": "rules_api_014",
            "doc_type": "api",
            "field_groups": ["state_logic"],
            "content": "## API: onStateChange\n\nSignature: .onStateChange(function(modification_dict) { ... })",
        },
    ]


def test_filter_evidence_for_dom_returns_layout_related_content_only() -> None:
    output = filter_evidence_for_fragment(_items(), "dom")

    assert "=== Example: minimal root gadget HTML ===" in output
    assert "login-form" in output
    assert "form submit with prevent_default" not in output
    assert "state-driven rendering skeleton" not in output
    assert "## " not in output


def test_filter_evidence_for_events_includes_submit_pattern_and_example() -> None:
    output = filter_evidence_for_fragment(_items(), "events")

    assert "=== Pattern: form submit with prevent_default ===" in output
    assert "=== Example: RSVP.Queue chain in submit handler ===" in output
    assert ".onEvent(\"submit\", handler, false, true)" in output
    assert "new RSVP.Queue()" in output
    assert output.count("submit handler") == 1


def test_filter_evidence_for_render_includes_state_rendering_and_dom_ownership() -> None:
    output = filter_evidence_for_fragment(_items(), "render")

    assert "=== Rule: DOM ownership + state-driven updates ===" in output
    assert "=== Pattern: state-driven rendering skeleton ===" in output
    assert "All DOM writes MUST happen in onStateChange." in output
    assert "Keep DOM writes in onStateChange" in output
    assert "Signature: .onStateChange" not in output
    assert output.count("DOM writes") <= 2


def test_filter_evidence_for_fragment_returns_default_message_when_empty() -> None:
    output = filter_evidence_for_fragment([], "dom")

    assert output == "(No specific evidence for this section. Follow the rules in system prompt.)"
