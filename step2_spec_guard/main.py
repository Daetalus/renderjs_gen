from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from step2_spec_guard.graph import run_step2_guard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Step2 Spec Guard")
    parser.add_argument("--spec", required=True, help="Path to draft component_spec.json")
    parser.add_argument("--out-spec", default="./component_spec.final.json")
    parser.add_argument("--out-constraints", default="./constraints_bundle.json")
    parser.add_argument("--out-issues", default="./issues.final.json")
    parser.add_argument("--out-report", default="./repair_report.json")
    parser.add_argument("--out-run-report", default=None)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--recursion-limit", type=int, default=20)
    return parser.parse_args()


def _log(message: str) -> None:
    print(f"[step2_spec_guard] {message}", flush=True)


def _write_json(path: str, payload: object) -> None:
    started = time.perf_counter()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(f"wrote {path} in {elapsed_ms:.1f} ms")


def main() -> None:
    cli_started = time.perf_counter()
    args = parse_args()
    _log(f"loading draft spec from {args.spec}")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))

    state = run_step2_guard(
        {
            "spec": spec,
            "round": 0,
            "max_rounds": max(0, int(args.max_rounds)),
            "repair_report": {},
            "termination_reason": "pending",
        },
        recursion_limit=max(1, int(args.recursion_limit)),
    )

    _write_json(args.out_spec, state.get("spec", {}))
    _write_json(args.out_constraints, state.get("constraints", {}))
    _write_json(args.out_issues, {"issues": state.get("issues", [])})
    _write_json(args.out_report, state.get("repair_report", {}))
    if args.out_run_report:
        run_report = {
            "termination_reason": state.get("termination_reason"),
            "final_ready": state.get("final_ready"),
            "validation_summary": state.get("validation_summary", {}),
            "round": state.get("round", 0),
            "max_rounds": state.get("max_rounds", 0),
        }
        _write_json(args.out_run_report, run_report)
    elapsed_ms = (time.perf_counter() - cli_started) * 1000.0
    _log(f"cli completed in {elapsed_ms:.1f} ms")


if __name__ == "__main__":
    main()
