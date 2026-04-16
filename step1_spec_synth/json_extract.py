from __future__ import annotations

import json


def _try_parse_json_object_text(candidate: str, *, depth: int = 0) -> str | None:
    stripped = candidate.strip()
    if not stripped or depth > 2:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return stripped
    if isinstance(parsed, str):
        return _try_parse_json_object_text(parsed, depth=depth + 1)
    return None


def _strip_outer_code_fence(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return None
    lines = stripped.splitlines()
    if len(lines) < 2:
        return None
    first_line = lines[0].strip()
    last_line = lines[-1].strip()
    if not first_line.startswith("```") or last_line != "```":
        return None
    return "\n".join(lines[1:-1]).strip()


def _extract_fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    lines = text.splitlines()
    inside = False
    current: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            if inside:
                blocks.append("\n".join(current).strip())
                current = []
                inside = False
            else:
                inside = True
            continue
        if inside:
            current.append(line)
    return [block for block in blocks if block]


def _scan_balanced_json_objects(text: str) -> list[str]:
    candidates: list[str] = []
    depth = 0
    in_string = False
    escape = False
    start: int | None = None

    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == "\"":
                in_string = False
            continue

        if char == "\"":
            in_string = True
            continue

        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue

        if char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : index + 1].strip())
                start = None

    return candidates


def extract_json_object_text(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        raise RuntimeError("LLM text is empty after stripping.")

    direct = _try_parse_json_object_text(text)
    if direct is not None:
        return direct

    fenced = _strip_outer_code_fence(text)
    if fenced is not None:
        direct_fenced = _try_parse_json_object_text(fenced)
        if direct_fenced is not None:
            return direct_fenced
        for candidate in _scan_balanced_json_objects(fenced):
            parsed = _try_parse_json_object_text(candidate)
            if parsed is not None:
                return parsed

    for block in _extract_fenced_blocks(text):
        direct_block = _try_parse_json_object_text(block)
        if direct_block is not None:
            return direct_block
        for candidate in _scan_balanced_json_objects(block):
            parsed = _try_parse_json_object_text(candidate)
            if parsed is not None:
                return parsed

    for candidate in _scan_balanced_json_objects(text):
        parsed = _try_parse_json_object_text(candidate)
        if parsed is not None:
            return parsed

    raise RuntimeError("LLM text did not contain a valid JSON object.")
