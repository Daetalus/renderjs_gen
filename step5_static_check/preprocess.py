from __future__ import annotations


def strip_strings_and_comments(js_code: str) -> str:
    """Strip comments and replace JS string literals with a placeholder.

    Newline characters are preserved so line numbers remain stable enough for
    static checks.
    """

    out: list[str] = []
    index = 0
    length = len(js_code)
    state = "code"
    quote = ""

    while index < length:
        char = js_code[index]
        nxt = js_code[index + 1] if index + 1 < length else ""

        if state == "code":
            if char == "/" and nxt == "/":
                state = "line_comment"
                index += 2
                continue
            if char == "/" and nxt == "*":
                state = "block_comment"
                index += 2
                continue
            if char in {"'", '"', "`"}:
                state = "string"
                quote = char
                out.append('"__STR__"')
                index += 1
                continue
            out.append(char)
            index += 1
            continue

        if state == "line_comment":
            if char == "\n":
                out.append("\n")
                state = "code"
            index += 1
            continue

        if state == "block_comment":
            if char == "*" and nxt == "/":
                state = "code"
                index += 2
                continue
            if char == "\n":
                out.append("\n")
            index += 1
            continue

        if state == "string":
            if char == "\\":
                index += 2
                continue
            if quote == "`" and char == "\n":
                out.append("\n")
                index += 1
                continue
            if char == quote:
                state = "code"
                quote = ""
                index += 1
                continue
            if char == "\n":
                out.append("\n")
                state = "code"
                quote = ""
                index += 1
                continue
            index += 1
            continue

    return "".join(out)


__all__ = ["strip_strings_and_comments"]
