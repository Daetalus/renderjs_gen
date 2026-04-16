from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

from inference_client import (
    DEFAULT_INFERENCE_BASE_URL,
    DEFAULT_INFERENCE_MODEL,
    DEFAULT_TIMEOUT,
    InferenceClient,
    LlamaCppClient,
)
from pipeline_state import PipelineState
from step4_codegen.node import step4_node


DEFAULT_MODEL = DEFAULT_INFERENCE_MODEL
DEFAULT_LLM_BASE_URL = DEFAULT_INFERENCE_BASE_URL
DEFAULT_API_KEY = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Step4 Fragment Generation + Assembly")
    parser.add_argument("--spec", required=True, help="Path to component_spec.final.json")
    parser.add_argument("--evidence", required=True, help="Path to evidence_pack.json")
    parser.add_argument("--contract", default=None, help="Optional path to generation_contract.json override")
    parser.add_argument("--out-dir", default="./generated", help="Output directory for generated files")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model name")
    parser.add_argument("--base-url", default=DEFAULT_LLM_BASE_URL, help="LLM base URL")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", DEFAULT_API_KEY), help="LLM API key")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-request timeout seconds")
    parser.add_argument("--summary-out", default=None, help="Optional JSON path for step4 summary")
    return parser.parse_args()


def _log(message: str) -> None:
    print(f"[step4_codegen] {message}", flush=True)


def _load_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _write_json(path: str, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"wrote {target}")


def _to_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "renderjs-gadget"


def _copy_runtime_files(out_dir: Path) -> list[str]:
    copied: list[str] = []
    for name in ("rsvp.js", "renderjs.js"):
        src = Path(name)
        if not src.exists():
            continue
        dst = out_dir / name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def generate_files(
    *,
    spec: dict[str, Any],
    evidence: dict[str, Any],
    out_dir: Path,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_LLM_BASE_URL,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    contract: dict[str, Any] | None = None,
    client: InferenceClient | None = None,
    **_ignored_kwargs: Any,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    generation_contract = contract or evidence.get("generation_contract") or {}

    llm_client = client or LlamaCppClient(
        base_url=base_url,
        model=model,
        api_key=api_key or None,
        timeout=float(timeout),
    )
    state = PipelineState(
        run_id="step4_standalone",
        out_dir=str(out_dir),
        status="running",
        spec=spec,
        generation_contract=generation_contract,
        evidence_pack=evidence,
    )
    next_state = step4_node(state, client=llm_client)
    if next_state.status == "aborted":
        raise RuntimeError(f"Step4 failed: {next_state.abort_reason or 'unknown_error'}")

    slug = _to_slug(str(spec.get("gadget_name") or spec.get("page_goal") or "renderjs-gadget"))
    html_path = out_dir / f"gadget_{slug}.html"
    js_path = out_dir / f"gadget_{slug}.js"
    html_path.write_text(next_state.code_html, encoding="utf-8")
    js_path.write_text(next_state.code_js, encoding="utf-8")
    copied_runtime = _copy_runtime_files(out_dir)

    summary = {
        "status": next_state.status,
        "warnings": list(next_state.warnings),
        "abort_reason": next_state.abort_reason,
        "generated_files": [str(html_path), str(js_path), *copied_runtime],
        "fragment_artifacts": dict(next_state.artifacts),
        "prompt_versions": dict(next_state.prompt_versions),
        "slug": slug,
    }
    return summary


def main() -> None:
    started = time.perf_counter()
    args = parse_args()
    spec = _load_json(args.spec)
    evidence = _load_json(args.evidence)
    contract = _load_json(args.contract) if args.contract else None

    summary = generate_files(
        spec=spec,
        evidence=evidence,
        contract=contract,
        out_dir=Path(args.out_dir),
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    if args.summary_out:
        _write_json(args.summary_out, summary)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(f"generated {len(summary['generated_files'])} files in {elapsed_ms:.1f} ms")
    for path in summary["generated_files"]:
        _log(f"generated: {path}")
    if summary["warnings"]:
        for warning in summary["warnings"]:
            _log(f"warning: {warning}")


if __name__ == "__main__":
    main()
