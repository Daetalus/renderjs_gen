# AGENTS.md — RenderJS Code Generation Pipeline

## Project Overview

This repository implements a workflow-based RenderJS code generator. It turns a
natural-language requirement into a single-gadget RenderJS page through a
deterministic-first pipeline:

- Step1: structured specification synthesis
- Step2: deterministic specification guard
- Step3: evidence retrieval and generation contract construction
- Step4: fragment generation plus deterministic assembly
- Step5: static validation

The project uses llama.cpp-compatible inference for generation, EmbeddingGemma
for retrieval embeddings, and ChromaDB as the local vector store.

## Architecture

```
NL requirement
→ Step1 (LLM: spec)
→ Step2 (deterministic: guard)
→ Step3 (embedding search: evidence + contract)
→ Step4 (Fragment Generation + Assembly)
→ Step5 (deterministic: static check)
```

Step4 is intentionally fragmented:

- 4a state_init: deterministic
- 4b DOM template: LLM
- bridge: deterministic selector extraction
- 4c event handlers: LLM
- 4d render logic: LLM
- 4f assembly: deterministic

## Key Design Choice

The central design decision is to avoid one-shot full-file generation.

RenderJS is a sparse, rule-heavy framework. Smaller models drift easily when
they must simultaneously generate DOM structure, async chains, event bindings,
and framework-correct rendering logic. This project reduces that failure mode by:

- moving deterministic work out of the LLM path
- retrieving only focused framework evidence
- generating narrow fragments instead of whole files
- assembling the final gadget with a fixed skeleton
- validating the output locally with static checks

## Directory Structure

```
renderjs_gen/
  run.py                    # Unified Step1-Step5 runner
  pipeline_driver.py        # Thin compatibility wrapper around run.py
  pipeline_state.py         # PipelineState dataclass
  inference_client.py       # LLM abstraction
  embedding_client.py       # EmbeddingGemma client
  chroma_embedding.py       # ChromaDB embedding function
  step1_spec_synth/
    main.py
    node.py
    schema.py
  step2_spec_guard/
    main.py
    node.py
    graph.py
    rules.py
    state.py
  step3_evidence_builder/
    main.py
    node.py
    graph.py
    query_planner.py
    contract_builder.py
  step4_codegen/
    main.py
    node.py
    fragments.py
    fragment_bridge.py
    assembler.py
    skeleton.py
    deterministic.py
    evidence_filter.py
  step5_static_check/
    main.py
    node.py
    checkers.py
    preprocess.py
prompts/
  step1_system.md
  step1_fewshots.json
  step1_user_template.md
  step4b_dom_system.md
  step4b_dom_user.md
  step4c_events_system.md
  step4c_events_user.md
  step4d_render_system.md
  step4d_render_user.md
corpus/
  renderjs_corpus_api_rules.md
  renderjs_corpus_patterns.md
  renderjs_corpus_examples.md
  renderjs_corpus_glossary.md
scripts/
  build_vectordb.py
tests/
  test_step1_node.py
  test_step2_node.py
  test_step3_node.py
  test_step4_node.py
  test_step5_node.py
  test_run_pipeline.py
artifacts/                  # Example pipeline output committed as visible sample
```

## Technical Notes

1. Step1 uses structured JSON output and schema validation.
2. Step2 repairs sparse specifications deterministically, including missing
   `ui_plan` backfilling.
3. Step3 retrieves evidence from the local ChromaDB collection in `./chroma_db/`
   using EmbeddingGemma query/document prompt separation.
4. Step4 uses fragment generation plus deterministic assembly rather than
   monolithic code generation.
5. Step5 strips comments and string literals before regex-based checks to reduce
   false positives.

## Coding Conventions

- Python 3.11+ with type hints
- Pydantic for structured model validation
- Dataclasses for pipeline state
- Each step node is a pure `(PipelineState) -> PipelineState` transform
- Prefer deterministic logic whenever possible

## How to Run

```bash
python scripts/build_vectordb.py
python -m run --request "Create a login form gadget" --api-key "<shared-key>"
python -m run --only-step 4 --artifacts-dir ./pipeline_artifacts --out-dir ./generated --step4-api-key "<key>"
```
