from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pipeline_state import PipelineState
import run


def _args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base = {
        "request": "Create a login form.",
        "stdin": False,
        "only_step": None,
        "handoff_mode": "memory",
        "save_artifacts": False,
        "artifacts_dir": str(tmp_path / "artifacts"),
        "out_dir": str(tmp_path / "generated"),
        "print_intermediate": False,
        "persist_dir": str(tmp_path / "chroma_db"),
        "collection": "renderjs_poc_v3",
        "embedding_url": "http://embed.example",
        "step1_model": "model-a",
        "step1_base_url": "http://llm.example",
        "step1_api_key": "k1",
        "step1_timeout": 30.0,
        "step4_model": "model-b",
        "step4_base_url": "http://llm.example",
        "step4_api_key": "k2",
        "step4_timeout": 30.0,
        "output_spec": None,
        "output_constraints": None,
        "output_issues": None,
        "output_evidence": None,
        "output_query_plan": None,
        "output_contract": None,
        "output_static_report": None,
        "summary_out": None,
        "input_spec": None,
        "input_constraints": None,
        "input_issues": None,
        "input_evidence": None,
        "input_contract": None,
        "input_html": None,
        "input_js": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_full_pipeline_memory_mode_runs_all_steps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        run,
        "_run_step1",
        lambda requirement, args: (
            PipelineState(
                request=requirement,
                status="ready",
                component_spec_draft={"task_type": "form", "page_goal": "Login"},
                prompt_versions={"step1": "abc"},
            ),
            {"status": "ready"},
        ),
    )
    monkeypatch.setattr(
        run,
        "_run_step2",
        lambda state: state.with_updates(
            spec={"task_type": "form", "page_goal": "Login"},
            constraints={"forbidden_patterns": []},
            issues=[],
        ),
    )
    monkeypatch.setattr(
        run,
        "_run_step3",
        lambda state, args: state.with_updates(
            query_plan={"queries": []},
            evidence_pack={"items": [], "stats": {}, "generation_contract": {"allowed_api_names": ["setState"]}},
            generation_contract={"allowed_api_names": ["setState"], "required_state_keys": [], "required_dom_selectors": []},
        ),
    )

    def fake_step4(state: PipelineState, args: SimpleNamespace, fragment_root: Path, generated_root: Path):
        generated_root.mkdir(parents=True, exist_ok=True)
        html = generated_root / "gadget_login.html"
        js = generated_root / "gadget_login.js"
        html.write_text("<html><head><script src=\"./rsvp.js\"></script><script src=\"./renderjs.js\"></script><script src=\"./gadget_login.js\"></script></head><body></body></html>", encoding="utf-8")
        js.write_text("rJS(window).setState({});", encoding="utf-8")
        return state.with_updates(
            status="ready",
            code_html=html.read_text(encoding="utf-8"),
            code_js=js.read_text(encoding="utf-8"),
        ), {"generated_files": [str(html), str(js)], "status": "ready"}

    monkeypatch.setattr(run, "_run_step4", fake_step4)
    monkeypatch.setattr(
        run,
        "_run_step5",
        lambda state: state.with_updates(static_report={"passed": True, "error_count": 0, "warning_count": 0}, status="passed"),
    )

    code = run._run_full_pipeline(_args(tmp_path), run._paths(tmp_path / "artifacts"))

    assert code == 0
    assert (tmp_path / "artifacts" / "step4" / "summary.json").exists()
    assert (tmp_path / "artifacts" / "step5" / "static_report.json").exists()


def test_full_pipeline_disk_mode_reads_persisted_step_outputs(monkeypatch, tmp_path: Path) -> None:
    def fake_step1(requirement: str, args: SimpleNamespace):
        return PipelineState(status="ready", component_spec_draft={"task_type": "display", "page_goal": "Draft"}), {"status": "ready"}

    def fake_step2(state: PipelineState):
        assert state.component_spec_draft == {"task_type": "display", "page_goal": "Draft"}
        return state.with_updates(spec={"task_type": "display", "page_goal": "FromDisk"}, constraints={}, issues=[])

    def fake_step3(state: PipelineState, args: SimpleNamespace):
        assert state.spec == {"task_type": "display", "page_goal": "FromDisk"}
        return state.with_updates(
            query_plan={"queries": []},
            evidence_pack={"items": [], "stats": {}, "generation_contract": {}},
            generation_contract={},
        )

    def fake_step4(state: PipelineState, args: SimpleNamespace, fragment_root: Path, generated_root: Path):
        assert state.spec == {"task_type": "display", "page_goal": "FromDisk"}
        generated_root.mkdir(parents=True, exist_ok=True)
        html = generated_root / "gadget_display.html"
        js = generated_root / "gadget_display.js"
        html.write_text("<html><head><script src=\"./rsvp.js\"></script><script src=\"./renderjs.js\"></script><script src=\"./gadget_display.js\"></script></head><body></body></html>", encoding="utf-8")
        js.write_text("rJS(window).setState({});", encoding="utf-8")
        return state.with_updates(status="ready"), {"generated_files": [str(html), str(js)], "status": "ready"}

    def fake_step5(state: PipelineState):
        assert "gadget_display.js" in state.code_js or state.code_js == "rJS(window).setState({});"
        return state.with_updates(static_report={"passed": True, "error_count": 0, "warning_count": 0}, status="passed")

    monkeypatch.setattr(run, "_run_step1", fake_step1)
    monkeypatch.setattr(run, "_run_step2", fake_step2)
    monkeypatch.setattr(run, "_run_step3", fake_step3)
    monkeypatch.setattr(run, "_run_step4", fake_step4)
    monkeypatch.setattr(run, "_run_step5", fake_step5)

    code = run._run_full_pipeline(_args(tmp_path, handoff_mode="disk"), run._paths(tmp_path / "artifacts"))

    assert code == 0
    assert json.loads((tmp_path / "artifacts" / "step2" / "component_spec.final.json").read_text(encoding="utf-8"))["page_goal"] == "FromDisk"


def test_single_step_five_always_writes_report(monkeypatch, tmp_path: Path) -> None:
    html = tmp_path / "gadget.html"
    js = tmp_path / "gadget.js"
    contract = tmp_path / "contract.json"
    html.write_text("<html></html>", encoding="utf-8")
    js.write_text("rJS(window);", encoding="utf-8")
    contract.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run,
        "_run_step5",
        lambda state: state.with_updates(static_report={"passed": True, "error_count": 0, "warning_count": 0}, status="passed"),
    )

    args = _args(
        tmp_path,
        only_step=5,
        input_html=str(html),
        input_js=str(js),
        input_contract=str(contract),
        output_static_report=str(tmp_path / "static_report.json"),
    )

    code = run._run_single_step(args, run._paths(tmp_path / "artifacts"))

    assert code == 0
    assert (tmp_path / "static_report.json").exists()


def test_shared_api_key_is_used_for_step1_and_step4(monkeypatch, tmp_path: Path) -> None:
    observed: list[str] = []

    class FakeClient:
        def __init__(self, *, base_url: str, model: str, api_key: str | None, timeout: float) -> None:
            del base_url, model, timeout
            observed.append(str(api_key))
            self.model = "fake-model"

    monkeypatch.setattr(run, "LlamaCppClient", FakeClient)
    monkeypatch.setattr(
        run,
        "step1_node",
        lambda state, client=None: state.with_updates(status="ready", component_spec_draft={"task_type": "display"}),
    )
    monkeypatch.setattr(
        run,
        "step4_node",
        lambda state, client=None: state.with_updates(status="ready", code_html="<html></html>", code_js="rJS(window);"),
    )
    monkeypatch.setattr(run, "_copy_runtime_files", lambda out_dir: [])

    args = _args(tmp_path, api_key="shared-key", step1_api_key=None, step4_api_key=None)
    step1_state, _ = run._run_step1("Create a page", args)
    _, summary = run._run_step4(
        step1_state.with_updates(spec={"page_goal": "Shared Key Test"}, generation_contract={}, evidence_pack={}),
        args,
        fragment_root=tmp_path / "fragments",
        generated_root=tmp_path / "generated",
    )

    assert summary["status"] == "ready"
    assert observed == ["shared-key", "shared-key"]
