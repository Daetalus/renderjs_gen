from __future__ import annotations

from typing import Any

from pipeline_state import PipelineState
from step5_static_check.checkers import CHECKERS, Issue
from step5_static_check.preprocess import strip_strings_and_comments


def _issue_dicts(issues: list[Issue]) -> list[dict[str, Any]]:
    return [issue.to_dict() for issue in issues]


def step5_node(state: PipelineState) -> PipelineState:
    html = state.code_html or ""
    js = state.code_js or ""
    contract = state.generation_contract or {}
    js_stripped = strip_strings_and_comments(js)

    all_issues: list[Issue] = []
    for checker in CHECKERS:
        all_issues.extend(checker(html, js, js_stripped, contract))

    errors = [issue for issue in all_issues if issue.severity == "error"]
    warnings = [issue for issue in all_issues if issue.severity != "error"]
    static_report = {
        "passed": len(errors) == 0,
        "errors": _issue_dicts(errors),
        "warnings": _issue_dicts(warnings),
        "error_count": len(errors),
        "warning_count": len(warnings),
    }

    next_status = state.status
    if len(errors) == 0 and next_status in {"ready", "running"}:
        next_status = "passed"
    elif len(errors) > 0:
        next_status = "failed"

    return state.with_updates(
        static_report=static_report,
        static_check_report=static_report,
        status=next_status,
    )


__all__ = ["step5_node"]
