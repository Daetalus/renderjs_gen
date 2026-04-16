from __future__ import annotations

from pathlib import Path

from inference_client import InferenceClient
from step4_codegen.main import generate_files


class SequenceClient(InferenceClient):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_schema=None,
        stream: bool = False,
        on_token=None,
        on_event=None,
    ) -> str:
        del messages, temperature, max_tokens, json_schema, stream, on_token, on_event
        if not self._responses:
            raise AssertionError("No more responses")
        return self._responses.pop(0)


def test_generate_files_writes_fragment_outputs_and_generated_files(tmp_path: Path) -> None:
    summary = generate_files(
        spec={
            "task_type": "form",
            "page_goal": "Create a login form",
            "state_schema": {
                "username": "string",
                "loading": "boolean",
                "error": "string",
            },
            "events": [{"type": "submit", "selector": ".login-form", "prevent_default": True}],
            "dom_requirements": [".login-form", ".username-input", ".submit-btn", ".error-msg"],
            "ui_plan": [],
            "acquisition_needs": [],
            "child_gadget_needs": [],
        },
        evidence={
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
            "generation_contract": {"forbidden_patterns": [".then(", "id="]},
        },
        out_dir=tmp_path,
        client=SequenceClient(
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
        ),
    )

    assert summary["status"] == "ready"
    generated_files = [Path(path) for path in summary["generated_files"]]
    assert any(path.name == "gadget_create-a-login-form.html" for path in generated_files)
    assert any(path.name == "gadget_create-a-login-form.js" for path in generated_files)
    assert (tmp_path / "step4" / "fragments" / "dom.html").exists()
