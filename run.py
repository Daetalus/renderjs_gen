from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from inference_client import LlamaCppClient
from pipeline_state import PipelineState
from step1_spec_synth.main import DEFAULT_BASE_URL as STEP1_DEFAULT_BASE_URL
from step1_spec_synth.main import DEFAULT_MODEL as STEP1_DEFAULT_MODEL
from step1_spec_synth.main import DEFAULT_TIMEOUT as STEP1_DEFAULT_TIMEOUT
from step1_spec_synth.node import step1_node
from step2_spec_guard.node import step2_node
from step3_evidence_builder.node import DEFAULT_STEP3_COLLECTION, DEFAULT_STEP3_PERSIST_DIR, step3_node
from step4_codegen.main import DEFAULT_API_KEY as STEP4_DEFAULT_API_KEY
from step4_codegen.main import DEFAULT_LLM_BASE_URL as STEP4_DEFAULT_BASE_URL
from step4_codegen.main import DEFAULT_MODEL as STEP4_DEFAULT_MODEL
from step4_codegen.node import step4_node
from step5_static_check.node import step5_node


@dataclass(slots=True)
class PipelinePaths:
    step1_spec: Path
    step1_report: Path
    step2_spec: Path
    step2_constraints: Path
    step2_issues: Path
    step3_evidence: Path
    step3_query_plan: Path
    step3_contract: Path
    step4_summary: Path
    step5_report: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Run Step1 -> Step5 pipeline")
    req_group = parser.add_mutually_exclusive_group(required=False)
    req_group.add_argument("--request", help="Natural-language component requirement")
    req_group.add_argument("--stdin", action="store_true", help="Read requirement from stdin")

    parser.add_argument("--only-step", type=int, choices=[1, 2, 3, 4, 5], default=None, help="Run only one step")
    parser.add_argument(
        "--handoff-mode",
        choices=["memory", "disk"],
        default="memory",
        help="Full pipeline only: pass step outputs in memory or through persisted files.",
    )
    parser.add_argument(
        "--save-artifacts",
        action="store_true",
        help="Persist intermediate JSON artifacts even when handoff-mode=memory.",
    )
    parser.add_argument("--artifacts-dir", default="./pipeline_artifacts", help="Intermediate artifact root directory")
    parser.add_argument("--out-dir", default="./generated", help="Final generated output directory")
    parser.add_argument("--print-intermediate", action="store_true", help="Print each step output JSON")

    parser.add_argument("--persist-dir", default=STEP3_DEFAULT_PERSIST_DIR, help="Chroma persist directory for Step3")
    parser.add_argument("--collection", default=DEFAULT_STEP3_COLLECTION, help="Chroma collection name for Step3")
    parser.add_argument("--embedding-url", default=None, help="Embedding API URL for Step3")

    parser.add_argument("--step1-model", default=STEP1_DEFAULT_MODEL, help="Step1 model")
    parser.add_argument("--step1-base-url", default=STEP1_DEFAULT_BASE_URL, help="Step1 base URL")
    parser.add_argument("--api-key", default=None, help="Shared API key for Step1 and Step4 when step-specific keys are not set")
    parser.add_argument("--step1-api-key", default=None, help="Step1 API key")
    parser.add_argument("--step1-timeout", type=float, default=STEP1_DEFAULT_TIMEOUT, help="Step1 timeout seconds")

    parser.add_argument("--step4-model", default=STEP4_DEFAULT_MODEL, help="Step4 model")
    parser.add_argument("--step4-base-url", default=STEP4_DEFAULT_BASE_URL, help="Step4 base URL")
    parser.add_argument(
        "--step4-api-key",
        default=os.getenv("OPENAI_API_KEY", STEP4_DEFAULT_API_KEY),
        help="Step4 API key",
    )
    parser.add_argument("--step4-timeout", type=float, default=120.0, help="Step4 timeout seconds")

    parser.add_argument("--output-spec", default=None, help="Explicit spec output path for single-step mode")
    parser.add_argument("--output-constraints", default=None, help="Explicit constraints output path for single-step mode")
    parser.add_argument("--output-issues", default=None, help="Explicit issues output path for single-step mode")
    parser.add_argument("--output-evidence", default=None, help="Explicit evidence output path for single-step mode")
    parser.add_argument("--output-query-plan", default=None, help="Explicit query plan output path for single-step mode")
    parser.add_argument("--output-contract", default=None, help="Explicit generation contract output path for single-step mode")
    parser.add_argument("--output-static-report", default=None, help="Explicit Step5 report output path")
    parser.add_argument("--summary-out", default=None, help="Optional full-pipeline summary JSON path")

    parser.add_argument("--input-spec", default=None, help="Input spec JSON for step2/3/4-only mode")
    parser.add_argument("--input-constraints", default=None, help="Input constraints JSON for step3-only mode")
    parser.add_argument("--input-issues", default=None, help="Input issues JSON for step3-only mode")
    parser.add_argument("--input-evidence", default=None, help="Input evidence JSON for step4-only mode")
    parser.add_argument("--input-contract", default=None, help="Input generation_contract JSON for step4/5-only mode")
    parser.add_argument("--input-html", default=None, help="Input generated HTML path for step5-only mode")
    parser.add_argument("--input-js", default=None, help="Input generated JS path for step5-only mode")
    return parser.parse_args()


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(step: str, message: str) -> None:
    print(f"[{step}][{_ts()}] {message}", flush=True)


def _print_step_box(step: int, total: int, title: str) -> None:
    label = f" STEP {step}/{total} - {title} "
    width = max(64, len(label) + 4)
    border = "*" * width
    print()
    print(border)
    print("*" + label.center(width - 2) + "*")
    print(border)


def _to_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "renderjs-gadget"


def _load_json_required(path: str, label: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"{label} file not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {target}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[saved] {path}")


def _print_json_if_needed(title: str, payload: Any, enabled: bool) -> None:
    if not enabled:
        return
    print(f"[{title}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_requirement(args: argparse.Namespace) -> str:
    if args.request:
        return args.request.strip()
    if args.stdin:
        return sys.stdin.read().strip()
    print("Please enter your component requirement in natural language:")
    return input("> ").strip()


def _paths(artifacts_dir: Path) -> PipelinePaths:
    return PipelinePaths(
        step1_spec=artifacts_dir / "step1" / "component_spec.draft.json",
        step1_report=artifacts_dir / "step1" / "run_report.json",
        step2_spec=artifacts_dir / "step2" / "component_spec.final.json",
        step2_constraints=artifacts_dir / "step2" / "constraints_bundle.json",
        step2_issues=artifacts_dir / "step2" / "issues.final.json",
        step3_evidence=artifacts_dir / "step3" / "evidence_pack.json",
        step3_query_plan=artifacts_dir / "step3" / "query_plan.json",
        step3_contract=artifacts_dir / "step3" / "generation_contract.json",
        step4_summary=artifacts_dir / "step4" / "summary.json",
        step5_report=artifacts_dir / "step5" / "static_report.json",
    )


def _copy_runtime_files(out_dir: Path) -> list[str]:
    copied: list[str] = []
    for name in ("rsvp.js", "renderjs.js"):
        src = Path(name)
        if not src.exists():
            continue
        dst = out_dir / name
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def _run_step1(requirement: str, args: argparse.Namespace) -> tuple[PipelineState, dict[str, Any]]:
    api_key = args.step1_api_key or args.api_key
    if not api_key:
        raise ValueError("Full pipeline Step1 requires --step1-api-key.")
    _log("step1", "start")
    started = time.perf_counter()
    client = LlamaCppClient(
        base_url=args.step1_base_url,
        model=args.step1_model,
        api_key=api_key,
        timeout=float(args.step1_timeout),
    )
    state = PipelineState(request=requirement, status="running")
    next_state = step1_node(state, client=client)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    report = {
        "ok": next_state.status != "aborted",
        "model": client.model,
        "elapsed_ms": elapsed_ms,
        "retry_count": next_state.retry_counts.get("step1", 0),
        "prompt_versions": dict(next_state.prompt_versions),
        "status": next_state.status,
        "abort_reason": next_state.abort_reason,
    }
    _log("step1", f"done in {elapsed_ms:.1f} ms with status={next_state.status}")
    return next_state, report


def _run_step2(input_state: PipelineState) -> PipelineState:
    _log("step2", "start")
    started = time.perf_counter()
    next_state = step2_node(input_state)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log("step2", f"done in {elapsed_ms:.1f} ms with status={next_state.status or 'ready'}")
    return next_state


def _run_step3(input_state: PipelineState, args: argparse.Namespace) -> PipelineState:
    _log("step3", "start")
    started = time.perf_counter()
    next_state = step3_node(
        input_state,
        persist_dir=args.persist_dir,
        collection_name=args.collection,
        embedding_url=args.embedding_url,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log("step3", f"done in {elapsed_ms:.1f} ms with status={next_state.status or 'ready'}")
    return next_state


def _run_step4(input_state: PipelineState, args: argparse.Namespace, fragment_root: Path, generated_root: Path) -> tuple[PipelineState, dict[str, Any]]:
    api_key = args.step4_api_key or args.api_key
    if not api_key:
        raise ValueError("Full pipeline Step4 requires --step4-api-key.")
    _log("step4", "start")
    started = time.perf_counter()
    client = LlamaCppClient(
        base_url=args.step4_base_url,
        model=args.step4_model,
        api_key=api_key,
        timeout=float(args.step4_timeout),
    )
    state_for_step4 = input_state.with_updates(out_dir=str(fragment_root), status="running")
    next_state = step4_node(state_for_step4, client=client)
    if next_state.status == "aborted":
        raise RuntimeError(f"Step4 failed: {next_state.abort_reason or 'unknown_error'}")

    generated_root.mkdir(parents=True, exist_ok=True)
    slug = _to_slug(str((next_state.spec or {}).get("gadget_name") or (next_state.spec or {}).get("page_goal") or "renderjs-gadget"))
    html_path = generated_root / f"gadget_{slug}.html"
    js_path = generated_root / f"gadget_{slug}.js"
    html_path.write_text(next_state.code_html, encoding="utf-8")
    js_path.write_text(next_state.code_js, encoding="utf-8")
    copied_runtime = _copy_runtime_files(generated_root)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    summary = {
        "status": next_state.status,
        "warnings": list(next_state.warnings),
        "abort_reason": next_state.abort_reason,
        "generated_files": [str(html_path), str(js_path), *copied_runtime],
        "fragment_artifacts": dict(next_state.artifacts),
        "prompt_versions": dict(next_state.prompt_versions),
        "slug": slug,
        "elapsed_ms": elapsed_ms,
    }
    _log("step4", f"done in {elapsed_ms:.1f} ms with status={next_state.status}")
    return next_state, summary


def _run_step5(input_state: PipelineState) -> PipelineState:
    _log("step5", "start")
    started = time.perf_counter()
    next_state = step5_node(input_state)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log("step5", f"done in {elapsed_ms:.1f} ms with status={next_state.status}")
    return next_state


def _persist_step_outputs(
    state: PipelineState,
    *,
    step_number: int,
    paths: PipelinePaths,
    report: dict[str, Any] | None = None,
    step4_summary: dict[str, Any] | None = None,
    force: bool = False,
) -> None:
    if not force:
        return
    if step_number == 1:
        _write_json(paths.step1_spec, state.component_spec_draft or {})
        if report is not None:
            _write_json(paths.step1_report, report)
    elif step_number == 2:
        _write_json(paths.step2_spec, state.spec or {})
        _write_json(paths.step2_constraints, state.constraints or {})
        _write_json(paths.step2_issues, {"issues": state.issues or []})
    elif step_number == 3:
        _write_json(paths.step3_evidence, state.evidence_pack or {})
        _write_json(paths.step3_query_plan, state.query_plan or {})
        _write_json(paths.step3_contract, state.generation_contract or {})
    elif step_number == 4 and step4_summary is not None:
        _write_json(paths.step4_summary, step4_summary)
    elif step_number == 5:
        _write_json(paths.step5_report, state.static_report or {})


def _load_step2_state_from_files(paths: PipelinePaths) -> PipelineState:
    return PipelineState(
        component_spec_draft=_load_json_required(str(paths.step1_spec), "step1 spec"),
        spec_draft=_load_json_required(str(paths.step1_spec), "step1 spec"),
        spec=_load_json_required(str(paths.step1_spec), "step1 spec"),
        status="running",
    )


def _load_step3_state_from_files(paths: PipelinePaths) -> PipelineState:
    issues_payload = _load_json_required(str(paths.step2_issues), "step2 issues")
    return PipelineState(
        spec=_load_json_required(str(paths.step2_spec), "step2 spec"),
        constraints=_load_json_required(str(paths.step2_constraints), "step2 constraints"),
        issues=list(issues_payload.get("issues") or []),
        unresolved_issues=list(issues_payload.get("issues") or []),
        status="running",
    )


def _load_step4_state_from_files(paths: PipelinePaths) -> PipelineState:
    evidence = _load_json_required(str(paths.step3_evidence), "step3 evidence")
    contract_path = paths.step3_contract
    contract = _load_json_required(str(contract_path), "step3 contract")
    return PipelineState(
        spec=_load_json_required(str(paths.step2_spec), "step2 spec"),
        evidence_pack=evidence,
        generation_contract=contract,
        status="running",
    )


def _load_step5_state_from_files(html_path: Path, js_path: Path, contract_path: Path, prior_status: str = "running") -> PipelineState:
    return PipelineState(
        code_html=html_path.read_text(encoding="utf-8"),
        code_js=js_path.read_text(encoding="utf-8"),
        generation_contract=_load_json_required(str(contract_path), "generation contract"),
        status=prior_status,
    )


def _resolve_single_step_paths(args: argparse.Namespace, paths: PipelinePaths) -> dict[str, Path]:
    return {
        "step1_spec": Path(args.output_spec) if args.output_spec else paths.step1_spec,
        "step2_spec": Path(args.output_spec) if args.output_spec else paths.step2_spec,
        "step2_constraints": Path(args.output_constraints) if args.output_constraints else paths.step2_constraints,
        "step2_issues": Path(args.output_issues) if args.output_issues else paths.step2_issues,
        "step3_evidence": Path(args.output_evidence) if args.output_evidence else paths.step3_evidence,
        "step3_query_plan": Path(args.output_query_plan) if args.output_query_plan else paths.step3_query_plan,
        "step3_contract": Path(args.output_contract) if args.output_contract else paths.step3_contract,
        "step5_report": Path(args.output_static_report) if args.output_static_report else paths.step5_report,
    }


def _run_single_step(args: argparse.Namespace, paths: PipelinePaths) -> int:
    step = int(args.only_step)
    resolved = _resolve_single_step_paths(args, paths)

    if step == 1:
        _print_step_box(1, 1, "Spec Synth")
        requirement = _read_requirement(args)
        if not requirement:
            raise SystemExit("Empty requirement.")
        state, report = _run_step1(requirement, args)
        if state.component_spec_draft is None:
            raise RuntimeError("Step1 did not produce component_spec_draft.")
        _write_json(resolved["step1_spec"], state.component_spec_draft)
        _write_json(paths.step1_report, report)
        _print_json_if_needed("step1.spec", state.component_spec_draft, True)
        return 0 if state.status != "aborted" else 2

    if step == 2:
        _print_step_box(1, 1, "Spec Guard")
        input_spec = args.input_spec or str(paths.step1_spec)
        spec = _load_json_required(input_spec, "step1 spec")
        state = _run_step2(PipelineState(component_spec_draft=spec, spec_draft=spec, spec=spec, status="running"))
        _write_json(resolved["step2_spec"], state.spec or {})
        _write_json(resolved["step2_constraints"], state.constraints or {})
        _write_json(resolved["step2_issues"], {"issues": state.issues or []})
        _print_json_if_needed("step2.state", {"spec": state.spec, "constraints": state.constraints, "issues": state.issues}, True)
        return 0 if state.status != "aborted" else 2

    if step == 3:
        _print_step_box(1, 1, "Evidence Builder")
        spec_path = args.input_spec or str(paths.step2_spec)
        constraints_path = args.input_constraints or str(paths.step2_constraints)
        issues_path = args.input_issues or str(paths.step2_issues)
        issues_payload = _load_json_required(issues_path, "step2 issues")
        state = _run_step3(
            PipelineState(
                spec=_load_json_required(spec_path, "step2 spec"),
                constraints=_load_json_required(constraints_path, "step2 constraints"),
                issues=list(issues_payload.get("issues") or []),
                unresolved_issues=list(issues_payload.get("issues") or []),
                status="running",
            ),
            args,
        )
        _write_json(resolved["step3_evidence"], state.evidence_pack or {})
        _write_json(resolved["step3_query_plan"], state.query_plan or {})
        _write_json(resolved["step3_contract"], state.generation_contract or {})
        _print_json_if_needed("step3.evidence", state.evidence_pack, True)
        return 0 if state.status != "aborted" else 2

    if step == 4:
        _print_step_box(1, 1, "Code Generator")
        spec_path = args.input_spec or str(paths.step2_spec)
        evidence_path = args.input_evidence or str(paths.step3_evidence)
        contract_path = args.input_contract or str(paths.step3_contract)
        state, summary = _run_step4(
            PipelineState(
                spec=_load_json_required(spec_path, "step2 spec"),
                evidence_pack=_load_json_required(evidence_path, "step3 evidence"),
                generation_contract=_load_json_required(contract_path, "step3 contract"),
                status="running",
            ),
            args,
            fragment_root=Path(args.artifacts_dir) / "step4",
            generated_root=Path(args.out_dir),
        )
        _write_json(paths.step4_summary, summary)
        _print_json_if_needed("step4.summary", summary, True)
        return 0 if state.status != "aborted" else 2

    if step == 5:
        _print_step_box(1, 1, "Static Check")
        if not args.input_html or not args.input_js:
            raise ValueError("Step5 requires --input-html and --input-js in single-step mode.")
        contract_path = args.input_contract or str(paths.step3_contract)
        state = _run_step5(
            _load_step5_state_from_files(
                html_path=Path(args.input_html),
                js_path=Path(args.input_js),
                contract_path=Path(contract_path),
                prior_status="running",
            )
        )
        _write_json(resolved["step5_report"], state.static_report or {})
        _print_json_if_needed("step5.static_report", state.static_report, True)
        return 0 if state.status == "passed" else 1

    raise ValueError(f"Unsupported only-step value: {step}")


def _run_full_pipeline(args: argparse.Namespace, paths: PipelinePaths) -> int:
    requirement = _read_requirement(args)
    if not requirement:
        raise SystemExit("Empty requirement.")

    persist_intermediate = args.handoff_mode == "disk" or args.save_artifacts
    print_enabled = args.print_intermediate

    _print_step_box(1, 5, "Spec Synth")
    step1_state, step1_report = _run_step1(requirement, args)
    _persist_step_outputs(step1_state, step_number=1, paths=paths, report=step1_report, force=persist_intermediate)
    _print_json_if_needed("step1.spec", step1_state.component_spec_draft, print_enabled)
    if step1_state.status == "aborted":
        return 2

    state_for_step2 = step1_state.with_updates(spec=step1_state.component_spec_draft)
    if args.handoff_mode == "disk":
        state_for_step2 = _load_step2_state_from_files(paths)

    _print_step_box(2, 5, "Spec Guard")
    step2_state = _run_step2(state_for_step2)
    _persist_step_outputs(step2_state, step_number=2, paths=paths, force=persist_intermediate)
    _print_json_if_needed("step2.state", {"spec": step2_state.spec, "constraints": step2_state.constraints, "issues": step2_state.issues}, print_enabled)
    if step2_state.status == "aborted":
        return 2

    state_for_step3 = step2_state
    if args.handoff_mode == "disk":
        state_for_step3 = _load_step3_state_from_files(paths)

    _print_step_box(3, 5, "Evidence Builder")
    step3_state = _run_step3(state_for_step3, args)
    _persist_step_outputs(step3_state, step_number=3, paths=paths, force=persist_intermediate)
    _print_json_if_needed("step3.evidence", step3_state.evidence_pack, print_enabled)
    if step3_state.status == "aborted":
        return 2

    state_for_step4 = step3_state
    if args.handoff_mode == "disk":
        state_for_step4 = _load_step4_state_from_files(paths)

    _print_step_box(4, 5, "Code Generator")
    step4_state, step4_summary = _run_step4(
        state_for_step4,
        args,
        fragment_root=Path(args.artifacts_dir) / "step4",
        generated_root=Path(args.out_dir),
    )
    _persist_step_outputs(step4_state, step_number=4, paths=paths, step4_summary=step4_summary, force=persist_intermediate or True)
    _print_json_if_needed("step4.summary", step4_summary, print_enabled)

    generated_files = [Path(path) for path in step4_summary.get("generated_files") or []]
    html_path = next((path for path in generated_files if path.suffix == ".html"), None)
    js_path = next((path for path in generated_files if path.suffix == ".js" and path.name not in {"rsvp.js", "renderjs.js"}), None)
    if html_path is None or js_path is None:
        raise RuntimeError("Step4 did not produce expected gadget HTML/JS files.")

    state_for_step5 = step4_state
    if args.handoff_mode == "disk":
        state_for_step5 = _load_step5_state_from_files(
            html_path=html_path,
            js_path=js_path,
            contract_path=paths.step3_contract,
            prior_status=step4_state.status,
        )

    _print_step_box(5, 5, "Static Check")
    step5_state = _run_step5(state_for_step5)
    _persist_step_outputs(step5_state, step_number=5, paths=paths, force=persist_intermediate or True)
    _print_json_if_needed("step5.static_report", step5_state.static_report, print_enabled)

    final_summary = {
        "status": step5_state.status,
        "step1_report": step1_report,
        "step4_summary": step4_summary,
        "static_report": step5_state.static_report,
        "artifacts_dir": str(Path(args.artifacts_dir)),
        "out_dir": str(Path(args.out_dir)),
        "handoff_mode": args.handoff_mode,
    }
    if args.summary_out:
        _write_json(Path(args.summary_out), final_summary)

    print()
    print("[done] Step1 -> Step5 pipeline completed.")
    print(f"[status] {step5_state.status}")
    print(f"[output_dir] {Path(args.out_dir)}")
    print(f"[artifacts_dir] {Path(args.artifacts_dir)}")

    if step5_state.status == "aborted":
        return 2
    if step5_state.status == "failed":
        return 1
    return 0


def main() -> int:
    args = _parse_args()
    paths = _paths(Path(args.artifacts_dir))
    if args.only_step is not None:
        return _run_single_step(args, paths)
    return _run_full_pipeline(args, paths)


if __name__ == "__main__":
    raise SystemExit(main())
