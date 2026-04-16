# RenderJS Code Generator

A workflow-based code generator for single-gadget RenderJS pages.

This project turns a natural-language requirement into RenderJS HTML and JS
through a deterministic-first pipeline:

1. Step1: synthesize a structured spec from the user request
2. Step2: repair and normalize the spec deterministically
3. Step3: retrieve relevant RenderJS evidence from a local vector database
4. Step4: generate focused code fragments and assemble the final gadget
5. Step5: run static validation on the generated output

The design goal is to make framework-specific generation more reliable for a
small model by moving as much work as possible into deterministic processing,
retrieval, and validation.

## Why This Exists

RenderJS is a niche JavaScript framework with a much smaller public corpus than
mainstream frameworks such as React or Vue. General-purpose LLMs can produce
plausible RenderJS code, but they often drift on framework-specific constraints:

- DOM writes must stay inside `onStateChange`
- async chains should use `RSVP.Queue`
- global DOM access is forbidden
- selector consistency matters across DOM, events, and render logic

This repository addresses that by replacing one-shot code generation with a
structured workflow plus static checks.

## Architecture

```text
Natural-language requirement
→ Step1  Spec synthesis (LLM)
→ Step2  Spec guard (deterministic)
→ Step3  Evidence builder (embedding search + contract)
→ Step4  Fragment generation + deterministic assembly
→ Step5  Static check
```

Step4 is intentionally fragmented:

- 4a `state_init`: deterministic
- 4b DOM template: LLM
- bridge: deterministic selector extraction from actual DOM output
- 4c event handlers: LLM
- 4d render logic: LLM
- 4f assembly: deterministic

This keeps each LLM call narrow and reduces framework drift.

## Current Status

Implemented:

- Step1 through Step5
- unified runner for full pipeline and single-step execution
- local ChromaDB-backed evidence retrieval
- fragment-based Step4 generation
- static validation of generated HTML and JS
- committed example output under [`artifacts/`](/home/sun/workspace/renderjs_gen/artifacts)

Not implemented yet:

- Step6 patch loop
- interactive feedback loop
- persistent memory system
- web UI

## Repository Layout

```text
renderjs_gen/
  run.py
  pipeline_driver.py
  pipeline_state.py
  inference_client.py
  embedding_client.py
  chroma_embedding.py
  step1_spec_synth/
  step2_spec_guard/
  step3_evidence_builder/
  step4_codegen/
  step5_static_check/
  prompts/
  corpus/
  scripts/
  tests/
  artifacts/
```

## Dependencies

Main dependencies are listed in [`requirements.txt`](/home/sun/workspace/renderjs_gen/requirements.txt).

This repository currently uses:

- `langchain`
- `langgraph`
- `pytest`
- `chromadb`
- `requests`
- `pydantic`

You also need:

- a llama.cpp-compatible inference endpoint for Step1 and Step4
- an embedding endpoint for EmbeddingGemma

## Build the Vector Database

Build the local ChromaDB collection from the corpus:

```bash
python scripts/build_vectordb.py
```

By default this writes to `./chroma_db/` and creates the collection
`renderjs_poc_v3`.

## Run the Full Pipeline

Use the unified runner:

```bash
python -m run \
  --request "Create a login form with username, password, and a submit button." \
  --api-key "<shared-key>"
```

If Step1 and Step4 use different keys, pass them separately:

```bash
python -m run \
  --request "Create a login form with username, password, and a submit button." \
  --step1-api-key "<step1-key>" \
  --step4-api-key "<step4-key>"
```

The runner supports two handoff modes:

- `--handoff-mode memory`
  Step outputs are passed in memory
- `--handoff-mode disk`
  Each step writes files and the next step reads them back

Example:

```bash
python -m run \
  --request "Create a login form with username, password, and a submit button." \
  --handoff-mode disk \
  --artifacts-dir ./pipeline_artifacts \
  --out-dir ./generated \
  --api-key "<shared-key>"
```

## Run Individual Steps

Each step can also run independently.

Step1:

```bash
python -m step1_spec_synth.main \
  --request "Create a login form with username, password, and a submit button." \
  --out ./artifacts/step1_draft.json \
  --api-key "<key>"
```

Step2:

```bash
python -m step2_spec_guard.main \
  --spec ./artifacts/step1_draft.json \
  --out-spec ./artifacts/component_spec.final.json \
  --out-constraints ./artifacts/constraints_bundle.json \
  --out-issues ./artifacts/issues.final.json
```

Step3:

```bash
python -m step3_evidence_builder.main \
  --spec ./artifacts/component_spec.final.json \
  --constraints ./artifacts/constraints_bundle.json \
  --issues ./artifacts/issues.final.json \
  --out ./artifacts/evidence_pack.json \
  --out-query-plan ./artifacts/query_plan.json \
  --out-generation-contract ./artifacts/generation_contract.json
```

Step4:

```bash
python -m step4_codegen.main \
  --spec ./artifacts/component_spec.final.json \
  --evidence ./artifacts/evidence_pack.json \
  --contract ./artifacts/generation_contract.json \
  --out-dir ./artifacts/step4_generated \
  --api-key "<key>"
```

Step5:

```bash
python -m step5_static_check.main \
  --html ./artifacts/step4_generated/gadget_a-minimal-login-form-with-username-password-and-a-submit-button.html \
  --js ./artifacts/step4_generated/gadget_a-minimal-login-form-with-username-password-and-a-submit-button.js \
  --contract ./artifacts/generation_contract.json \
  --out ./artifacts/static_report.json
```

## Example Output

A visible example pipeline result is committed under
[`artifacts/`](/home/sun/workspace/renderjs_gen/artifacts), including:

- Step1 draft
- Step2 normalized spec and constraints
- Step3 evidence pack and generation contract
- Step4 generated gadget files and intermediate fragments

## Tests

Run the focused regression suite:

```bash
./venv/bin/python -m pytest \
  tests/test_step1_node.py \
  tests/test_step2_node.py \
  tests/test_step3_node.py \
  tests/test_step4_node.py \
  tests/test_step5_node.py \
  tests/test_run_pipeline.py
```

## Notes

- `renderjs.js` and `rsvp.js` are committed runtime assets and are copied next
  to generated gadgets.
- `chroma_db/` is intentionally ignored because it is a local build artifact.
- `step1_prompt_bundle.json` is a debug artifact and is intentionally ignored.
