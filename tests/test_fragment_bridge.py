from __future__ import annotations

from step4_codegen.fragment_bridge import build_fragment_bridge


def test_build_fragment_bridge_extracts_classes_and_maps_selectors() -> None:
    dom_html = """
<form class="login-form root" data-role="login">
  <input type="text" class="username-input form-control" name="username">
  <input type="password" class="password-input" name="password">
  <button type="submit" class="submit-btn primary-action">Login</button>
</form>
""".strip()
    spec = {
        "dom_requirements": [
            ".login-form",
            ".username-input",
            ".password_input",
            ".error-msg",
        ]
    }

    bridge = build_fragment_bridge(dom_html, spec)

    assert bridge["actual_classes"] == [
        "form-control",
        "login-form",
        "password-input",
        "primary-action",
        "root",
        "submit-btn",
        "username-input",
    ]
    assert bridge["selector_map"] == {
        ".login-form": ".login-form",
        ".username-input": ".username-input",
        ".password_input": ".password-input",
    }
    assert bridge["missing_selectors"] == [".error-msg"]
    assert ("role", "login") in bridge["data_attrs"]
    assert {"tag": "input", "type": "text", "name": "username", "class": "username-input form-control"} in bridge["form_elements"]
    assert {"tag": "button", "type": "submit", "class": "submit-btn primary-action"} in bridge["form_elements"]
