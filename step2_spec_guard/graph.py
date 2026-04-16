from __future__ import annotations

import time
from typing import Any

from pipeline_state import PipelineState
from step2_spec_guard.node import step2_node
from step2_spec_guard.state import Step2State


def _log(message: str) -> None:
    print(f"[step2_spec_guard] {message}", flush=True)


def _coerce_pipeline_state(initial_state: Step2State) -> PipelineState:
    spec = initial_state.get("spec")
    return PipelineState(
        component_spec_draft=spec,
        spec_draft=spec,
        spec=spec,
        constraints=initial_state.get("constraints"),
        issues=list(initial_state.get("issues") or []),
        unresolved_issues=list(initial_state.get("unresolved_issues") or []),
    )


class _DeterministicStep2Graph:
    def invoke(self, initial_state: Step2State, config: dict[str, Any] | None = None) -> Step2State:
        return run_step2_guard(initial_state)


def build_step2_graph(**_: Any) -> _DeterministicStep2Graph:
    return _DeterministicStep2Graph()


def _build_validation_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    blocking_count = sum(1 for issue in issues if issue.get("severity") == "blocking")
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    categories: dict[str, int] = {}
    for issue in issues:
        category = str(issue.get("category") or "unknown")
        categories[category] = categories.get(category, 0) + 1
    return {
        "final_ready": blocking_count == 0 and error_count == 0,
        "blocking_count": blocking_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "category_counts": categories,
    }


def run_step2_guard(
    initial_state: Step2State,
    *,
    recursion_limit: int = 20,
    **_: Any,
) -> Step2State:
    del recursion_limit
    started = time.perf_counter()
    _log("run start deterministic_step2_node=enabled")

    pipeline_state = _coerce_pipeline_state(initial_state)
    result = step2_node(pipeline_state)
    issues = list(result.issues or [])
    validation_summary = _build_validation_summary(issues)
    termination_reason = "validated" if validation_summary["final_ready"] else "validated_with_warnings"
    if result.status == "aborted":
        termination_reason = result.abort_reason or "aborted"

    repair_report = {
        "rounds_attempted": 0,
        "termination_reason": termination_reason,
        "applied_fixes": len(issues),
        "unresolved_issue_ids": [issue.get("issue_id", "") for issue in issues if issue.get("issue_id")],
    }
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(
        "run done "
        f"in {elapsed_ms:.1f} ms "
        f"termination_reason={termination_reason} "
        f"final_ready={validation_summary['final_ready']} "
        f"issues={len(issues)}"
    )
    return {
        "spec": result.spec or {},
        "constraints": result.constraints or {},
        "issues": issues,
        "unresolved_issues": list(result.unresolved_issues or []),
        "applied_fixes": [],
        "repair_report": repair_report,
        "validation_summary": validation_summary,
        "round": 0,
        "max_rounds": int(initial_state.get("max_rounds", 0)),
        "termination_reason": termination_reason,
        "final_ready": bool(validation_summary["final_ready"]),
    }


__all__ = ["build_step2_graph", "run_step2_guard"]
