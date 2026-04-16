from __future__ import annotations

from step4_codegen.skeleton import HTML_SKELETON, JS_SKELETON


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def assemble_gadget(
    slug: str,
    title: str,
    state_init: str,
    acquired_methods: str,
    dom_template: str,
    event_handlers: str,
    render_logic: str,
    declare_methods: str | None = None,
) -> tuple[str, str]:
    chain_parts: list[str] = [state_init]

    if acquired_methods.strip():
        chain_parts.append(acquired_methods)
    if declare_methods and declare_methods.strip():
        chain_parts.append(declare_methods)
    if event_handlers.strip():
        chain_parts.append(event_handlers)

    chain_parts.append(
        '    .onStateChange(function (modification_dict) {\n'
        f"{indent(render_logic, 6)}\n"
        "    })"
    )

    html = HTML_SKELETON.format(
        title=title,
        slug=slug,
        dom_template=indent(dom_template, 4),
    )
    js = JS_SKELETON.format(chain_str="\n\n".join(chain_parts))
    return html, js
