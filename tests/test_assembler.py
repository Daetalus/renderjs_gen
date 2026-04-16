from __future__ import annotations

from step4_codegen.assembler import assemble_gadget


def test_assemble_gadget_wraps_iife_and_preserves_chain_order() -> None:
    html, js = assemble_gadget(
        slug="login_form",
        title="Login Form",
        state_init='    .setState({"username": "", "loading": false})',
        acquired_methods='    .declareAcquiredMethod("notifyParent", "notify")',
        dom_template='<form class="login-form"></form>',
        event_handlers='    .onEvent("submit", function () {\n      return this.changeState({loading: true});\n    }, false, true)',
        render_logic='var el = this.element;\nel.querySelector(".login-form").classList.toggle("is-loading", this.state.loading);',
        declare_methods='    .declareMethod("refresh", function () {\n      return this.changeState({loading: false});\n    })',
    )

    assert '<script src="./rsvp.js"></script>' in html
    assert '<script src="./renderjs.js"></script>' in html
    assert html.index("rsvp.js") < html.index("renderjs.js")

    assert js.startswith("/*global window, rJS, RSVP */")
    assert '(function (window, rJS, RSVP) {' in js
    assert '"use strict";' in js
    assert "rJS(window)" in js

    set_state_pos = js.index('.setState({"username": "", "loading": false})')
    acquired_pos = js.index('.declareAcquiredMethod("notifyParent", "notify")')
    method_pos = js.index('.declareMethod("refresh", function () {')
    event_pos = js.index('.onEvent("submit", function () {')
    render_pos = js.index(".onStateChange(function (modification_dict) {")

    assert set_state_pos < acquired_pos < method_pos < event_pos < render_pos
    assert 'var el = this.element;' in js
    assert 'el.querySelector(".login-form").classList.toggle("is-loading", this.state.loading);' in js
    assert "modification_dict" in js
    assert js.rstrip().endswith("}(window, rJS, RSVP));")
