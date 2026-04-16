from __future__ import annotations

from typing import Any, TypedDict


class Step2State(TypedDict, total=False):
    spec: dict[str, Any]
    constraints: dict[str, Any]
    issues: list[dict[str, Any]]
    unresolved_issues: list[dict[str, Any]]
    applied_fixes: list[dict[str, Any]]
    repair_report: dict[str, Any]
    validation_summary: dict[str, Any]
    round: int
    max_rounds: int
    termination_reason: str
    final_ready: bool
