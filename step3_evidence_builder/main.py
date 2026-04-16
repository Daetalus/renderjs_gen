from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from step3_evidence_builder.graph import run_step3_evidence_builder
from step3_evidence_builder.node import DEFAULT_STEP3_COLLECTION, DEFAULT_STEP3_PERSIST_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Step3 Evidence Builder")
    parser.add_argument("--spec", required=True, help="Path to component_spec.final.json")
    parser.add_argument("--constraints", required=True, help="Path to constraints_bundle.json")
    parser.add_argument("--issues", default=None, help="Optional path to issues.final.json")
    parser.add_argument("--out", default="./evidence_pack.json")
    parser.add_argument("--out-retrieval-report", default=None)
    parser.add_argument("--out-query-plan", default=None)
    parser.add_argument("--out-generation-contract", default=None)
    parser.add_argument("--persist-dir", default=DEFAULT_STEP3_PERSIST_DIR)
    parser.add_argument("--collection", default=DEFAULT_STEP3_COLLECTION)
    parser.add_argument("--embedding-url", default=None)
    parser.add_argument("--recursion-limit", type=int, default=20)
    return parser.parse_args()


def _log(message: str) -> None:
    print(f"[step3_evidence_builder] {message}", flush=True)


def _load_json(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _write_json(path: str, payload: object) -> None:
    started = time.perf_counter()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(f"wrote {path} in {elapsed_ms:.1f} ms")


def main() -> None:
    cli_started = time.perf_counter()
    args = parse_args()
    spec = _load_json(args.spec)
    constraints = _load_json(args.constraints)
    issues_payload = _load_json(args.issues) if args.issues else {}
    unresolved_issues = issues_payload.get("issues") or []
    if not isinstance(unresolved_issues, list):
        raise ValueError("issues JSON must contain a list at `issues`")
    state = run_step3_evidence_builder(
        {
            "spec": spec,
            "constraints": constraints,
            "unresolved_issues": unresolved_issues,
            "persist_dir": args.persist_dir,
            "embedding_url": args.embedding_url,
        },
        collection=args.collection,
        recursion_limit=max(1, int(args.recursion_limit)),
    )
    _write_json(args.out, state.get("evidence_pack", {}))
    if args.out_retrieval_report:
        _write_json(args.out_retrieval_report, state.get("retrieval_report", {}))
    if args.out_query_plan:
        _write_json(args.out_query_plan, state.get("query_plan", {}))
    if args.out_generation_contract:
        _write_json(args.out_generation_contract, state.get("generation_contract", {}))
    elapsed_ms = (time.perf_counter() - cli_started) * 1000.0
    _log(f"cli completed in {elapsed_ms:.1f} ms")


if __name__ == "__main__":
    main()
