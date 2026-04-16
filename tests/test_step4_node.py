from __future__ import annotations

from pathlib import Path

from inference_client import InferenceClient
from pipeline_state import PipelineState
from step4_codegen.fragments import EVENTS_TODO_PLACEHOLDER, RENDER_TODO_PLACEHOLDER
from step4_codegen.node import step4_node


class SequenceClient(InferenceClient):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_schema: dict | None = None,
        stream: bool = False,
        on_token=None,
        on_event=None,
    ) -> str:
        del temperature, max_tokens, json_schema, stream, on_token, on_event
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("No more fake responses available.")
        return self._responses.pop(0)


def _state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        run_id="run_step4_test",
        out_dir=str(tmp_path),
        status="running",
        spec={
            "task_type": "form",
            "page_goal": "Create a login form",
            "ui_plan": [
                {
                    "kind": "container",
                    "selector": ".root",
                    "children": [
                        {"kind": "input", "selector": ".username-input", "name": "username"},
                        {"kind": "button", "selector": ".submit-btn", "text": "Submit"},
                    ],
                }
            ],
            "state_schema": {
                "username": "string",
                "loading": "boolean",
                "error": "string",
            },
            "events": [
                {"type": "submit", "selector": ".login-form", "prevent_default": True},
            ],
            "dom_requirements": [
                ".login-form",
                ".username-input",
                ".submit-btn",
                ".error-msg",
            ],
            "acquisition_needs": [
                {"local_name": "notifyParent", "acquisition_name": "notify"},
            ],
            "child_gadget_needs": [],
        },
        generation_contract={
            "forbidden_patterns": [".then(", "id="],
        },
        evidence_pack={
            "items": [
                {
                    "id": "example_001",
                    "doc_type": "example",
                    "field_groups": ["layout_html"],
                    "content": "## Example\n\n<form class=\"login-form\"></form>",
                },
                {
                    "id": "pattern_001",
                    "doc_type": "pattern",
                    "field_groups": ["event_binding", "async_flow"],
                    "content": "## Pattern\n\nReturn new RSVP.Queue().push(...)",
                },
                {
                    "id": "rule_001",
                    "doc_type": "rule",
                    "field_groups": ["state_logic"],
                    "content": "## Rule\n\nDOM writes only in onStateChange.",
                },
            ],
        },
    )


def test_step4_node_builds_fragments_and_writes_artifacts(tmp_path: Path) -> None:
    client = SequenceClient(
        [
            """```html
<form class="login-form">
  <input type="text" class="username-input" name="username">
  <button type="submit" class="submit-btn">Submit</button>
  <span class="error-msg"></span>
</form>
```""",
            """```javascript
    .onEvent("submit", function () {
      var gadget = this;
      return gadget.changeState({loading: true});
    }, false, true)
```""",
            """```javascript
var el = this.element;
el.querySelector(".error-msg").textContent = this.state.error;
```""",
        ]
    )

    next_state = step4_node(_state(tmp_path), client=client)

    assert next_state.status == "ready"
    assert next_state.fragment_dom.startswith("<form class=\"login-form\">")
    assert next_state.fragment_bridge["selector_map"][".username-input"] == ".username-input"
    assert next_state.fragment_events.strip().startswith('.onEvent("submit"')
    assert 'el.querySelector(".error-msg").textContent = this.state.error;' in next_state.fragment_render
    assert '<script src="./rsvp.js"></script>' in (next_state.code_html or "")
    assert '    .setState({"username": "", "loading": false, "error": ""})' in (next_state.code_js or "")
    assert '.declareAcquiredMethod("notifyParent", "notify")' in (next_state.code_js or "")
    assert ".onStateChange(function (modification_dict) {" in (next_state.code_js or "")

    fragment_dir = tmp_path / "step4" / "fragments"
    assert (fragment_dir / "state_init.js").exists()
    assert (fragment_dir / "dom.html").exists()
    assert (fragment_dir / "bridge.json").exists()
    assert (fragment_dir / "events.js").exists()
    assert (fragment_dir / "render.js").exists()


def test_step4_node_uses_scoped_fragment_prompts(tmp_path: Path) -> None:
    client = SequenceClient(
        [
            """```html
<form class="login-form">
  <input type="text" class="username-input" name="username">
  <button type="submit" class="submit-btn">Submit</button>
  <span class="error-msg"></span>
</form>
```""",
            """```javascript
    .onEvent("submit", function () {
      return this.changeState({loading: true});
    }, false, true)
```""",
            """```javascript
var el = this.element;
el.querySelector(".error-msg").textContent = this.state.error;
```""",
        ]
    )

    step4_node(_state(tmp_path), client=client)

    assert len(client.calls) == 3
    dom_prompt = client.calls[0][1]["content"]
    events_prompt = client.calls[1][1]["content"]
    render_prompt = client.calls[2][1]["content"]

    assert len(dom_prompt) // 3 < 3000
    assert len(events_prompt) // 3 < 3000
    assert len(render_prompt) // 3 < 3000

    assert "## Relevant Evidence" in dom_prompt
    assert '<form class="login-form"></form>' in dom_prompt
    assert "RSVP.Queue submit" not in dom_prompt

    assert "Pattern" in events_prompt
    assert "RSVP.Queue().push" in events_prompt or "RSVP.Queue().push(...)" in events_prompt
    assert '<form class="login-form"></form>' not in events_prompt

    assert "DOM writes only in onStateChange." in render_prompt
    assert "RSVP.Queue submit" not in render_prompt


def test_step4_node_aborts_when_dom_fragment_generation_fails(tmp_path: Path) -> None:
    client = SequenceClient(["not fenced html", "still not fenced"])

    next_state = step4_node(_state(tmp_path), client=client)

    assert next_state.status == "aborted"
    assert next_state.abort_reason == "step4b_dom_generation_failed"
    assert next_state.code_html == ""
    assert next_state.code_js == ""


def test_step4_node_degrades_when_events_and_render_fail(tmp_path: Path) -> None:
    client = SequenceClient(
        [
            """```html
<form class="login-form">
  <input type="text" class="username-input" name="username">
  <button type="submit" class="submit-btn">Submit</button>
</form>
```""",
            "not fenced js",
            "still not fenced js",
            "not fenced render",
            "still not fenced render",
        ]
    )

    next_state = step4_node(_state(tmp_path), client=client)

    assert next_state.status == "degraded"
    assert next_state.fragment_events == EVENTS_TODO_PLACEHOLDER
    assert next_state.fragment_render == RENDER_TODO_PLACEHOLDER
    assert EVENTS_TODO_PLACEHOLDER in (next_state.code_js or "")
    assert "render logic generation failed" in (next_state.code_js or "")
