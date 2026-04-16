from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


def default_retry_counts() -> dict[str, int]:
    return {
        "step1": 0,
        "step4b": 0,
        "step4c": 0,
        "step4d": 0,
        "step6": 0,
    }


@dataclass(slots=True)
class PipelineState:
    request: str = ""
    run_id: str = ""
    out_dir: str = ""
    status: str = "ready"
    abort_reason: str = ""

    component_spec_draft: dict[str, Any] | None = None
    spec_draft: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    unresolved_issues: list[dict[str, Any]] = field(default_factory=list)

    query_plan: dict[str, Any] | None = None
    evidence_pack: dict[str, Any] | None = None
    generation_contract: dict[str, Any] | None = None

    fragment_state_init: str = ""
    fragment_dom: str = ""
    fragment_bridge: dict[str, Any] = field(default_factory=dict)
    fragment_events: str = ""
    fragment_render: str = ""
    fragment_methods: str = ""

    code_html: str = ""
    code_js: str = ""
    assembled_gadget: str = ""
    static_report: dict[str, Any] | None = None
    static_check_report: dict[str, Any] | None = None
    patch_result: str = ""
    final_output: str = ""

    artifacts: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    retry_counts: dict[str, int] = field(default_factory=default_retry_counts)

    def bump_retry(self, step: str) -> int:
        current = self.retry_counts.get(step, 0) + 1
        self.retry_counts[step] = current
        return current

    def with_updates(self, **changes: Any) -> "PipelineState":
        return replace(self, **changes)
