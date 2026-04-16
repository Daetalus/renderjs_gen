from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from inference_client import (
    DEFAULT_INFERENCE_BASE_URL,
    DEFAULT_INFERENCE_MODEL,
    DEFAULT_TIMEOUT as DEFAULT_CLIENT_TIMEOUT,
    LlamaCppClient,
)
from pipeline_state import PipelineState
from step1_spec_synth.node import step1_node
from step1_spec_synth.schema import ComponentSpecDraft


DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", DEFAULT_INFERENCE_BASE_URL)
DEFAULT_MODEL = os.getenv("LLM_MODEL", DEFAULT_INFERENCE_MODEL)
DEFAULT_TIMEOUT = DEFAULT_CLIENT_TIMEOUT


@dataclass
class RunReport:
    ok: bool
    model: str
    elapsed_ms: float
    retry_count: int
    prompt_versions: dict[str, str]
    status: str
    abort_reason: str


def log_cli(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [step1_spec_synth] {message}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step1 spec synthesis as a standalone command.")
    parser.add_argument("--request", type=str, help="Raw natural-language request.")
    parser.add_argument("--request-file", type=str, help="Path to a text file containing the request.")
    parser.add_argument("--out", type=str, help="Path to write the Step1 draft JSON.")
    parser.add_argument("--stdout", action="store_true", help="Print draft JSON to stdout.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--report-out", type=str, help="Optional path to write a run report JSON.")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help="LLM base URL.")
    parser.add_argument("--temperature", type=float, default=0.1, help="Reserved for compatibility; Step1 uses 0.1.")
    parser.add_argument("--max-tokens", type=int, default=1800, help="Reserved for compatibility with older callers.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Request timeout in seconds.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model name sent to the inference endpoint.")
    parser.add_argument("--api-key", type=str, help="API key for the inference endpoint.")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output from the LLM call.")
    parser.add_argument("--cache-prompt", action="store_true", help="Reserved for compatibility with older callers.")
    return parser.parse_args()


def load_request_text(args: argparse.Namespace) -> str:
    if args.request and args.request_file:
        raise ValueError("Provide either --request or --request-file, not both.")
    if args.request:
        text = args.request.strip()
    elif args.request_file:
        text = Path(args.request_file).read_text(encoding="utf-8").strip()
    else:
        raise ValueError("One of --request or --request-file is required.")
    if not text:
        raise ValueError("Request text is empty.")
    return text


def write_json(path: str | Path, data: Any, pretty: bool) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2 if pretty else None)
    Path(path).write_text(text + "\n", encoding="utf-8")


def resolve_prompt_dump_path(args: argparse.Namespace) -> Path:
    out_path = getattr(args, "out", None)
    report_out_path = getattr(args, "report_out", None)
    if out_path:
        base = Path(out_path)
        return base.with_name(f"{base.stem}.prompt_bundle.json")
    if report_out_path:
        base = Path(report_out_path)
        return base.with_name(f"{base.stem}.prompt_bundle.json")
    return Path.cwd() / "step1_prompt_bundle.json"


def synthesize_component_spec(args: argparse.Namespace) -> tuple[ComponentSpecDraft, RunReport]:
    cli_started = time.perf_counter()
    log_cli("Loading request text")
    load_started = time.perf_counter()
    request_text = load_request_text(args)
    log_cli(f"Loaded request in {(time.perf_counter() - load_started) * 1000.0:.1f} ms; chars={len(request_text)}")

    stream_enabled = not bool(getattr(args, "no_stream", False))
    started_at = time.perf_counter()
    api_key = getattr(args, "api_key", None)
    if api_key is not None:
        api_key = str(api_key).strip() or None
    if not api_key:
        raise ValueError("Step1 requires --api-key for the inference endpoint.")

    state = PipelineState(request=request_text)
    log_cli(
        f"Initializing inference client for {args.base_url.rstrip('/')}/v1/chat/completions "
        f"(model={getattr(args, 'model', DEFAULT_MODEL)}, timeout={float(args.timeout):.1f}s, "
        f"stream={stream_enabled}, auth={'yes' if bool(api_key) else 'no'})"
    )
    client = LlamaCppClient(
        base_url=args.base_url,
        timeout=float(args.timeout),
        model=str(getattr(args, "model", DEFAULT_MODEL)),
        api_key=api_key,
    )

    current_stream_phase = {"value": None, "seen_output": False}

    def _finish_stream_block() -> None:
        if current_stream_phase["seen_output"]:
            print(file=sys.stderr, flush=True)
            current_stream_phase["seen_output"] = False
        current_stream_phase["value"] = None

    def progress(message: str) -> None:
        elapsed_ms = (time.perf_counter() - cli_started) * 1000.0
        _finish_stream_block()
        log_cli(f"{message} | +{elapsed_ms:.1f} ms")

    def stream_callback(phase: str, chunk: str) -> None:
        if current_stream_phase["value"] != phase:
            if current_stream_phase["seen_output"]:
                print(file=sys.stderr, flush=True)
            current_stream_phase["value"] = phase
            current_stream_phase["seen_output"] = False
            log_cli(f"Streaming LLM output ({phase})")
        print(chunk, end="", file=sys.stderr, flush=True)
        current_stream_phase["seen_output"] = True

    def raw_output_callback(phase: str, text: str) -> None:
        _finish_stream_block()
        log_cli(f"LLM raw output begin ({phase})")
        print(text, file=sys.stderr, flush=True)
        log_cli(f"LLM raw output end ({phase})")

    def prompt_bundle_callback(bundle: dict[str, Any]) -> None:
        _finish_stream_block()
        prompt_dump_path = resolve_prompt_dump_path(args)
        prompt_dump_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_text = json.dumps(bundle, ensure_ascii=False, indent=2)
        log_cli("Prompt bundle begin")
        print(prompt_text, file=sys.stderr, flush=True)
        log_cli("Prompt bundle end")
        prompt_dump_path.write_text(prompt_text + "\n", encoding="utf-8")
        log_cli(f"Prompt bundle written to {prompt_dump_path}")

    log_cli("Starting Step1 synthesis")
    result = step1_node(
        state,
        client=client,
        progress=progress,
        stream_callback=(None if not stream_enabled else stream_callback),
        raw_output_callback=raw_output_callback,
        prompt_bundle_callback=prompt_bundle_callback,
    )
    _finish_stream_block()

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    log_cli(f"Step1 synthesis finished in {elapsed_ms:.1f} ms with status={result.status}")
    report = RunReport(
        ok=result.status != "aborted",
        model=client.model,
        elapsed_ms=elapsed_ms,
        retry_count=result.retry_counts.get("step1", 0),
        prompt_versions=dict(result.prompt_versions),
        status=result.status,
        abort_reason=result.abort_reason,
    )

    if result.component_spec_draft is None:
        message = result.errors[-1] if result.errors else "Step1 did not produce a component_spec_draft."
        raise RuntimeError(message)

    draft = ComponentSpecDraft.model_validate(result.component_spec_draft)
    return draft, report


def main() -> int:
    args = parse_args()
    try:
        draft, report = synthesize_component_spec(args)
    except ValueError as exc:
        log_cli(f"input error: {exc}")
        return 2
    except RuntimeError as exc:
        log_cli(f"step1 error: {exc}")
        return 3

    payload = draft.model_dump(mode="json")
    if args.out:
        log_cli(f"Writing draft JSON to {args.out}")
        write_json(args.out, payload, pretty=args.pretty)
    if args.stdout or not args.out:
        log_cli("Writing draft JSON to stdout")
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    if args.report_out:
        log_cli(f"Writing run report to {args.report_out}")
        write_json(args.report_out, asdict(report), pretty=True)
    log_cli("Step1 command completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
