from __future__ import annotations

import re
from typing import Any


_EMPTY_EVIDENCE_TEXT = "(No specific evidence for this section. Follow the rules in system prompt.)"


def _token_budget_to_chars(token_budget: int) -> int:
    return token_budget * 3


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _split_title_and_body(content: str) -> tuple[str, str]:
    text = content.strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("## "):
        title = lines[0][3:].strip()
        body = "\n".join(lines[1:]).strip()
        return title, body
    return "", text


def _format_item(item: dict[str, Any]) -> str:
    title, body = _split_title_and_body(str(item.get("content") or ""))
    if not body:
        body = title
    heading = f"=== {title or item.get('id') or 'Evidence'} ==="
    return f"{heading}\n{body.strip()}".strip()


def _has_field_group(item: dict[str, Any], groups: set[str]) -> bool:
    field_groups = item.get("field_groups") or []
    normalized = {str(group).strip() for group in field_groups if str(group).strip()}
    return bool(normalized & groups)


def _doc_type_allowed(item: dict[str, Any], allowed: set[str]) -> bool:
    return str(item.get("doc_type") or "").strip() in allowed


def _is_render_relevant(item: dict[str, Any]) -> bool:
    field_groups = item.get("field_groups") or []
    normalized_groups = [str(group).strip() for group in field_groups if str(group).strip()]
    content = str(item.get("content") or "")
    lowered = content.lower()

    if "signature:" in lowered and "onstatechange" not in lowered and "dom writes" not in lowered:
        return False

    if normalized_groups == ["state_logic"]:
        render_keywords = (
            "onstatechange",
            "state-driven",
            "dom writes",
            "this.element",
            "queryselector",
            "textcontent",
            "innerhtml",
            "classlist",
            "modification_dict",
            "render",
        )
        return any(keyword in lowered for keyword in render_keywords)

    return True


def filter_evidence_for_fragment(
    evidence_items: list[dict[str, Any]],
    fragment_name: str,
) -> str:
    if fragment_name == "dom":
        allowed_groups = {"layout_html"}
        allowed_doc_types = {"rule", "example"}
        max_chars = _token_budget_to_chars(800)
        extra_predicate = lambda item: True
    elif fragment_name == "events":
        allowed_groups = {"event_binding", "async_flow"}
        allowed_doc_types = {"rule", "pattern", "example"}
        max_chars = _token_budget_to_chars(1000)
        extra_predicate = lambda item: True
    elif fragment_name == "render":
        allowed_groups = {"state_logic"}
        allowed_doc_types = {"rule", "pattern", "example"}
        max_chars = _token_budget_to_chars(800)
        extra_predicate = _is_render_relevant
    else:
        raise ValueError(f"Unsupported fragment_name: {fragment_name}")

    selected: list[str] = []
    seen_blocks: set[str] = set()
    current_chars = 0

    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        if not _has_field_group(item, allowed_groups):
            continue
        if not _doc_type_allowed(item, allowed_doc_types):
            continue
        if not extra_predicate(item):
            continue

        block = _format_item(item)
        normalized = _normalize_text(block)
        if not normalized or normalized in seen_blocks:
            continue

        projected_chars = current_chars + len(block) + (7 if selected else 0)
        if selected and projected_chars > max_chars:
            break

        selected.append(block)
        seen_blocks.add(normalized)
        current_chars = projected_chars

    if not selected:
        return _EMPTY_EVIDENCE_TEXT
    return "\n\n---\n\n".join(selected)


__all__ = ["filter_evidence_for_fragment"]
