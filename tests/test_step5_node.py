from __future__ import annotations

from pipeline_state import PipelineState
from step5_static_check.node import step5_node


GOOD_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <script src="./rsvp.js"></script>
    <script src="./renderjs.js"></script>
    <script src="./gadget_login.js"></script>
  </head>
  <body>
    <form class="login-form">
      <input type="text" class="username-input">
      <input type="password" class="password-input">
      <button type="submit" class="submit-btn">Submit</button>
      <span class="error-msg"></span>
    </form>
  </body>
</html>
"""


GOOD_JS = """/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {
  "use strict";

  rJS(window)
    .setState({"username": "", "password": "", "error_message": "", "is_submitting": false})
    .onEvent("submit", function () {
      var gadget = this;
      return gadget.changeState({is_submitting: true});
    }, false, true)
    .onStateChange(function (modification_dict) {
      var el = this.element;
      el.querySelector(".error-msg").textContent = this.state.error_message;
    });
}(window, rJS, RSVP));
"""


def test_step5_node_passes_valid_renderjs_output() -> None:
    state = PipelineState(
        status="ready",
        code_html=GOOD_HTML,
        code_js=GOOD_JS,
        generation_contract={
            "allowed_api_names": ["setState", "changeState", "onStateChange", "onEvent"],
            "required_state_keys": ["username", "password", "error_message", "is_submitting"],
            "required_dom_selectors": [".login-form", ".username-input", ".password-input", ".submit-btn", ".error-msg"],
            "required_event_bindings": ["submit"],
        },
    )

    next_state = step5_node(state)

    assert next_state.status == "passed"
    assert next_state.static_report is not None
    assert next_state.static_report["passed"] is True
    assert next_state.static_report["error_count"] == 0
    assert next_state.static_check_report == next_state.static_report


def test_step5_node_reports_errors_and_warnings() -> None:
    bad_html = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <script src="./renderjs.js"></script>
  </head>
  <body>
    <div id="bad-root" class="login-form">
      <button class="submit-btn">Submit</button>
    </div>
  </body>
</html>
"""
    bad_js = """/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {
  "use strict";

  rJS(window)
    .setState({"username": ""})
    .ready(function () { return this; })
    .onEvent("click", function () {
      document.querySelector(".login-form").textContent = "bad";
      return promise.then(function () {});
    }, false, false);
}(window, rJS, RSVP));
"""

    state = PipelineState(
        status="ready",
        code_html=bad_html,
        code_js=bad_js,
        generation_contract={
            "allowed_api_names": ["setState", "changeState", "onStateChange", "onEvent"],
            "required_state_keys": ["username", "password"],
            "required_dom_selectors": [".login-form", ".username-input"],
            "required_event_bindings": ["submit"],
        },
    )

    next_state = step5_node(state)
    report = next_state.static_report or {}

    assert next_state.status == "failed"
    assert report["passed"] is False
    rules = {item["rule"] for item in report["errors"] + report["warnings"]}
    assert "no_then" in rules
    assert "no_id_attr" in rules
    assert "no_global_dom" in rules
    assert "dom_in_onstatechange" in rules
    assert "has_rsvp_js" in rules
    assert "has_paired_js" in rules
    assert "has_required_state_keys" in rules
    assert "has_required_selectors" in rules
    assert "has_required_events" in rules
    assert "api_whitelist" in rules
