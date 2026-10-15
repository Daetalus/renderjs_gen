# Step4 Fragment Generator + Assembler

Step4 generates one RenderJS gadget HTML/JS pair from:
- `component_spec.final.json`
- `evidence_pack.json`
- optional `generation_contract.json` override

It also writes fragment artifacts to `step4/fragments/` under the output directory.
If `renderjs.js` and `rsvp.js` exist in the project root, they are copied next to the generated gadget files.

## Run

```bash
python -m step4_codegen.main \
  --spec ./component_spec.final.json \
  --evidence ./evidence_pack.json \
  --out-dir ./generated \
  --base-url http://localhost:8080/v1 \
  --model 'bartowski/google_gemma-4-26B-A4B-it-GGUF:IQ4_XS' \
  --api-key 'YOUR_KEY' \
  --timeout 120
```

## Flow

- 4a deterministic `.setState(...)`
- 4b LLM DOM fragment
- bridge selector extraction
- 4c LLM event fragment
- 4d LLM render fragment
- 4f deterministic assembly

DOM failure aborts the step. Event/render failure degrade to TODO placeholders.

## Tests

```bash
python -m pytest tests/test_step4_main.py tests/test_step4_node.py tests/test_assembler.py tests/test_fragment_bridge.py
```
