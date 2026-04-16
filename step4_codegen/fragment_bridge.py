from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any


def _normalize_class_name(name: str) -> str:
    return name.strip().replace("_", "-").replace(".", "-").lower()


def fuzzy_match_class(expected: str, actuals: set[str]) -> str | None:
    normalized = _normalize_class_name(expected)
    for actual in sorted(actuals):
        if _normalize_class_name(actual) == normalized:
            return actual
    return None


def _selector_strings(dom_requirements: list[Any] | None) -> list[str]:
    selectors: list[str] = []
    for item in dom_requirements or []:
        if isinstance(item, str) and item.strip():
            selectors.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        selector = item.get("selector") or item.get("css_selector") or item.get("path")
        if isinstance(selector, str) and selector.strip():
            selectors.append(selector.strip())
    return selectors


class _FormElementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.form_elements: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag not in {"input", "textarea", "select", "button", "form"}:
            return
        item: dict[str, str] = {"tag": tag}
        for key in ("type", "name", "class", "data-role"):
            value = attr_map.get(key)
            if value:
                item[key.replace("-", "_")] = value
        self.form_elements.append(item)


def extract_form_elements(dom_html: str) -> list[dict[str, str]]:
    parser = _FormElementParser()
    parser.feed(dom_html)
    return parser.form_elements


def build_fragment_bridge(dom_html: str, spec: dict[str, Any]) -> dict[str, Any]:
    class_values = re.findall(r'class\s*=\s*"([^"]*)"', dom_html)
    class_values.extend(re.findall(r"class\s*=\s*'([^']*)'", dom_html))

    all_classes: set[str] = set()
    for class_value in class_values:
        for class_name in class_value.split():
            if class_name:
                all_classes.add(class_name)

    selector_map: dict[str, str] = {}
    missing_selectors: list[str] = []

    for selector in _selector_strings(spec.get("dom_requirements")):
        class_name = selector.lstrip(".")
        if class_name in all_classes:
            selector_map[selector] = selector
            continue
        match = fuzzy_match_class(class_name, all_classes)
        if match:
            selector_map[selector] = f".{match}"
        else:
            missing_selectors.append(selector)

    data_attrs = re.findall(r'data-([a-zA-Z0-9_-]+)\s*=\s*"([^"]*)"', dom_html)
    data_attrs.extend(re.findall(r"data-([a-zA-Z0-9_-]+)\s*=\s*'([^']*)'", dom_html))

    return {
        "actual_classes": sorted(all_classes),
        "selector_map": selector_map,
        "missing_selectors": missing_selectors,
        "form_elements": extract_form_elements(dom_html),
        "data_attrs": data_attrs,
        "dom_html": dom_html,
    }
