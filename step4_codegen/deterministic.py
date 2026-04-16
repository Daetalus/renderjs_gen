from __future__ import annotations

import json
from typing import Any


def _iter_state_fields(spec: dict[str, Any]) -> list[tuple[str, str]]:
    state_schema = spec.get("state_schema") or {}
    if isinstance(state_schema, dict):
        return [(str(key), str(value)) for key, value in state_schema.items()]

    fields: list[tuple[str, str]] = []
    if isinstance(state_schema, list):
        for item in state_schema:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            if not isinstance(name, str) or not name.strip():
                continue
            type_hint = item.get("field_type") or item.get("type") or "object"
            fields.append((name.strip(), str(type_hint)))
    return fields


def _default_value_for_type(type_hint: str) -> Any:
    normalized = type_hint.strip().lower()
    if normalized == "string":
        return ""
    if normalized == "boolean":
        return False
    if normalized == "number":
        return 0
    if normalized == "array":
        return []
    if normalized == "object":
        return {}
    return None


def generate_state_init(spec: dict[str, Any]) -> str:
    init_dict = {
        key: _default_value_for_type(type_hint)
        for key, type_hint in _iter_state_fields(spec)
    }
    return f"    .setState({json.dumps(init_dict, ensure_ascii=False)})"


def generate_acquired_methods(spec: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in spec.get("acquisition_needs") or []:
        if not isinstance(item, dict):
            continue
        local_name = item.get("local_name") or item.get("method_name")
        acquisition_name = item.get("acquisition_name") or item.get("public_name")
        if not isinstance(local_name, str) or not local_name.strip():
            continue
        if not isinstance(acquisition_name, str) or not acquisition_name.strip():
            continue
        lines.append(
            f'    .declareAcquiredMethod("{local_name.strip()}", "{acquisition_name.strip()}")'
        )
    return "\n".join(lines)
