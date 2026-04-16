from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pipeline_state import PipelineState
from step5_static_check.node import step5_node


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Step5 Static Check")
    parser.add_argument("--html", required=True, help="Path to generated gadget HTML file")
    parser.add_argument("--js", required=True, help="Path to generated gadget JS file")
    parser.add_argument("--contract", required=True, help="Path to generation_contract.json")
    parser.add_argument("--out", default="./static_report.json", help="Output path for static report JSON")
    return parser.parse_args()


def _log(message: str) -> None:
    print(f"[step5_static_check] {message}", flush=True)


def _load_json(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _write_json(path: str, payload: object) -> None:
    started = time.perf_counter()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(f"wrote {target} in {elapsed_ms:.1f} ms")


def main() -> None:
    started = time.perf_counter()
    args = parse_args()
    html = Path(args.html).read_text(encoding="utf-8")
    js = Path(args.js).read_text(encoding="utf-8")
    contract = _load_json(args.contract)
    state = PipelineState(
        status="running",
        code_html=html,
        code_js=js,
        generation_contract=contract,
    )
    next_state = step5_node(state)
    _write_json(args.out, next_state.static_report or {})
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _log(f"cli completed in {elapsed_ms:.1f} ms with status={next_state.status}")


if __name__ == "__main__":
    main()
