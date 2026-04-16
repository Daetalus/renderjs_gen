from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


KNOWN_RENDERJS_APIS: set[str] = {
    "ready",
    "declareMethod",
    "declareService",
    "declareJob",
    "onEvent",
    "onLoop",
    "setState",
    "onStateChange",
    "changeState",
    "declareGadget",
    "getDeclaredGadget",
    "dropGadget",
    "allowPublicAcquisition",
    "declareAcquiredMethod",
    "getInterfaceList",
    "getMethodList",
    "getRequiredCSSList",
    "getRequiredJSList",
    "getPath",
    "getTitle",
}

DOM_WRITE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.textContent\s*=", "Mutate DOM text only inside onStateChange."),
    (r"\.innerHTML\s*=", "Mutate DOM HTML only inside onStateChange."),
    (r"\.appendChild\s*\(", "Append DOM nodes only inside onStateChange."),
    (r"\.removeChild\s*\(", "Remove DOM nodes only inside onStateChange."),
    (r"\.replaceChildren\s*\(", "Replace DOM nodes only inside onStateChange."),
    (r"\.insertAdjacentHTML\s*\(", "Write DOM only inside onStateChange."),
    (r"\.classList\.(?:add|remove|toggle)\s*\(", "Toggle classes only inside onStateChange."),
)


@dataclass(slots=True)
class Issue:
    rule: str
    severity: str
    line: int
    snippet: str
    fix_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, max(index, 0)) + 1


def _line_snippet(text: str, index: int) -> str:
    lines = text.splitlines()
    line = _line_number(text, index) - 1
    if 0 <= line < len(lines):
        return lines[line].strip()
    return ""


def _extract_head(html: str) -> str:
    match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _extract_body(html: str) -> str:
    match = re.search(r"<body\b[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else html


def _extract_set_state_keys(js: str) -> set[str]:
    match = re.search(r"\.setState\s*\(\s*\{(?P<body>.*?)\}\s*\)", js, re.DOTALL)
    if not match:
        return set()
    body = match.group("body")
    return {
        key.strip()
        for key in re.findall(r'["\']?([A-Za-z_][A-Za-z0-9_\-]*)["\']?\s*:', body)
        if key.strip()
    }


def _extract_html_classes(html: str) -> set[str]:
    class_names: set[str] = set()
    for value in re.findall(r'class\s*=\s*"([^"]*)"', html, re.IGNORECASE):
        class_names.update(token for token in value.split() if token)
    for value in re.findall(r"class\s*=\s*'([^']*)'", html, re.IGNORECASE):
        class_names.update(token for token in value.split() if token)
    return class_names


def _extract_renderjs_api_calls(js_stripped: str) -> set[str]:
    calls = {name for name in re.findall(r"\.([A-Za-z][A-Za-z0-9_]*)\s*\(", js_stripped) if name in KNOWN_RENDERJS_APIS}
    if re.search(r"new\s+RSVP\.Queue\s*\(", js_stripped):
        calls.add("RSVP.Queue")
    return calls


def check_no_then(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html, js, contract
    match = re.search(r"\.then\s*\(", js_stripped)
    if not match:
        return []
    return [
        Issue(
            rule="no_then",
            severity="error",
            line=_line_number(js_stripped, match.start()),
            snippet=_line_snippet(js_stripped, match.start()),
            fix_hint="replace_with_rsvp_queue",
        )
    ]


def check_no_id_attr(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del js, js_stripped, contract
    body = _extract_body(html)
    match = re.search(r"\bid\s*=", body, re.IGNORECASE)
    if not match:
        return []
    return [
        Issue(
            rule="no_id_attr",
            severity="error",
            line=_line_number(body, match.start()),
            snippet=_line_snippet(body, match.start()),
            fix_hint="replace_id_with_class",
        )
    ]


def check_no_global_dom(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html, js, contract
    issues: list[Issue] = []
    patterns = (
        r"document\.querySelector\s*\(",
        r"document\.querySelectorAll\s*\(",
        r"document\.getElementById\s*\(",
        r"document\.body\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, js_stripped):
            issues.append(
                Issue(
                    rule="no_global_dom",
                    severity="error",
                    line=_line_number(js_stripped, match.start()),
                    snippet=_line_snippet(js_stripped, match.start()),
                    fix_hint="use_this_element_queryselector",
                )
            )
    return issues


def check_dom_in_onstatechange(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html, contract
    issues: list[Issue] = []
    in_on_state_change = False
    brace_depth = 0
    waiting_for_block = False

    for line_number, line in enumerate(js_stripped.splitlines(), start=1):
        if ".onStateChange(" in line:
            waiting_for_block = True
        opens = line.count("{")
        closes = line.count("}")
        if waiting_for_block and opens > 0:
            in_on_state_change = True
            brace_depth += opens - closes
            waiting_for_block = False
        elif in_on_state_change:
            brace_depth += opens - closes

        if not in_on_state_change:
            for pattern, fix_hint in DOM_WRITE_PATTERNS:
                if re.search(pattern, line):
                    issues.append(
                        Issue(
                            rule="dom_in_onstatechange",
                            severity="error",
                            line=line_number,
                            snippet=line.strip(),
                            fix_hint=fix_hint,
                        )
                    )
                    break

        if in_on_state_change and brace_depth <= 0:
            in_on_state_change = False
            brace_depth = 0

    return issues


def check_has_rsvp_js(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del js, js_stripped, contract
    head = _extract_head(html)
    if re.search(r'<script[^>]+src="[^"]*rsvp\.js"', head, re.IGNORECASE):
        return []
    return [Issue(rule="has_rsvp_js", severity="error", line=1, snippet="HEAD", fix_hint="add_rsvp_js_script")]


def check_has_renderjs_js(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del js, js_stripped, contract
    head = _extract_head(html)
    if re.search(r'<script[^>]+src="[^"]*renderjs\.js"', head, re.IGNORECASE):
        return []
    return [Issue(rule="has_renderjs_js", severity="error", line=1, snippet="HEAD", fix_hint="add_renderjs_js_script")]


def check_has_paired_js(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del js, js_stripped, contract
    head = _extract_head(html)
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', head, re.IGNORECASE)
    paired = [src for src in scripts if src.lower().endswith(".js") and not src.endswith("rsvp.js") and not src.endswith("renderjs.js")]
    if paired:
        return []
    return [Issue(rule="has_paired_js", severity="error", line=1, snippet="HEAD", fix_hint="add_paired_gadget_js")]


def check_required_state_keys(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html, js_stripped
    required = {str(item).strip() for item in contract.get("required_state_keys") or [] if str(item).strip()}
    if not required:
        return []
    actual = _extract_set_state_keys(js)
    missing = sorted(required - actual)
    return [
        Issue(
            rule="has_required_state_keys",
            severity="warning",
            line=1,
            snippet=key,
            fix_hint="add_missing_state_key_to_setstate",
        )
        for key in missing
    ]


def check_required_selectors(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del js, js_stripped
    required = {str(item).strip() for item in contract.get("required_dom_selectors") or [] if str(item).strip()}
    if not required:
        return []
    classes = _extract_html_classes(_extract_body(html))
    missing = sorted(selector for selector in required if selector.startswith(".") and selector[1:] not in classes)
    return [
        Issue(
            rule="has_required_selectors",
            severity="warning",
            line=1,
            snippet=selector,
            fix_hint="add_missing_selector_to_html",
        )
        for selector in missing
    ]


def check_has_required_events(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html
    required = {str(item).strip() for item in contract.get("required_event_bindings") or [] if str(item).strip()}
    if not required:
        return []
    present = {
        event_type
        for event_type in re.findall(r'\.onEvent\s*\(\s*["\']([^"\']+)["\']', js_stripped)
        if event_type.strip()
    }
    missing = sorted(required - present)
    return [
        Issue(
            rule="has_required_events",
            severity="warning",
            line=1,
            snippet=event_type,
            fix_hint="add_missing_onevent_binding",
        )
        for event_type in missing
    ]


def check_api_whitelist(html: str, js: str, js_stripped: str, contract: dict[str, Any]) -> list[Issue]:
    del html, js
    allowed = {str(item).strip() for item in contract.get("allowed_api_names") or [] if str(item).strip()}
    if not allowed:
        return []
    used = _extract_renderjs_api_calls(js_stripped)
    unexpected = sorted(api for api in used if api not in allowed)
    return [
        Issue(
            rule="api_whitelist",
            severity="warning",
            line=1,
            snippet=api,
            fix_hint="remove_or_authorize_api_usage",
        )
        for api in unexpected
    ]


CHECKERS = (
    check_no_then,
    check_no_id_attr,
    check_no_global_dom,
    check_dom_in_onstatechange,
    check_has_rsvp_js,
    check_has_renderjs_js,
    check_has_paired_js,
    check_required_state_keys,
    check_required_selectors,
    check_has_required_events,
    check_api_whitelist,
)


__all__ = [
    "CHECKERS",
    "Issue",
    "check_api_whitelist",
    "check_dom_in_onstatechange",
    "check_has_paired_js",
    "check_has_renderjs_js",
    "check_has_required_events",
    "check_has_rsvp_js",
    "check_no_global_dom",
    "check_no_id_attr",
    "check_no_then",
    "check_required_selectors",
    "check_required_state_keys",
]
