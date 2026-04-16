# Step2 Spec Guard

Step2 remains a LangGraph workflow, but every node is deterministic-only and local-only:

`load_constraints -> validate_spec -> repair_deterministic -> validate_spec -> ... -> finalize`

## Constraint sources

Step2 loads constraints only from:

- `renderjs_core_canon.py`
- `step2_spec_guard/step2_rule_pack.py`

Step2 does not:

- call any LLM
- perform any RAG
- query vector stores
- retrieve from external corpora

## Run Step2

```bash
python -m step2_spec_guard.main \
  --spec ./component_spec.json \
  --max-rounds 3 \
  --recursion-limit 20 \
  --out-spec ./component_spec.final.json \
  --out-constraints ./constraints_bundle.json \
  --out-issues ./issues.final.json \
  --out-report ./repair_report.json \
  --out-run-report ./step2_run_report.json
```

Outputs:

- `component_spec.final.json`
- `constraints_bundle.json`
- `issues.final.json`
- `repair_report.json`
- `step2_run_report.json`
