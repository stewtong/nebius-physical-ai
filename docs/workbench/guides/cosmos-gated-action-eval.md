# Cosmos-gated action eval

**The hook:** a robot needs an action gate, not just a caption. This guide uses
the shipped fixture to ask whether a warehouse robot should `act`, `wait`,
`replan`, or `reject` before attempting a pick-and-place task.

The first path is fully offline. The hosted path uses Token Factory and
`nvidia/Cosmos3-Super-Reasoner` only after you choose to provide credentials.

## Ingredients

- **Robot task:** pick the red box and place it in the tote.
- **Dataset:** eight synthetic, license-clean fixture scenes.
- **Offline check:** `vlm-eval benchmark --backend stub`.
- **Hosted check:** optional Token Factory reasoning with
  `nvidia/Cosmos3-Super-Reasoner`.
- **Report:** a helper that parses action-gate JSON and reports unsafe
  pass-through, false reject, invalid-gate, and per-risk rates.

## Fast path

Run the binary compatibility check with the offline `stub` backend:

```bash
npa workbench vlm-eval benchmark \
  --dataset npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/benchmark.json \
  --output /tmp/cosmos3-gate-benchmark.json \
  --backend stub \
  --thresholds 0.5,0.8,0.9 \
  --rubrics action_gate,strict_safety \
  --models fixture-stub \
  --format json
```

Then run the deterministic action-gate report fixture:

```bash
python npa/scripts/report_cosmos_gated_action_eval.py summarize \
  --manifest npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/benchmark.json \
  --parsed-gates npa/tests/fixtures/cosmos_gated_action_eval/action_gates.jsonl \
  --vlm-eval-report /tmp/cosmos3-gate-benchmark.json \
  --output-dir /tmp/cosmos3-gate/report \
  --run-id cosmos3-gate-fixture \
  --result-type fixture
```

Open `/tmp/cosmos3-gate/report/summary.md`. The deterministic fixture includes
one unsafe pass-through and one malformed parser output so denominator handling
is visible without a live model call.

## What just happened

`vlm-eval` preserves the existing Workbench binary scoring surface:
`expected_label: pass` means the safe gate is `act`, and
`expected_label: fail` means the safe gate is any blocking action.

The report helper rereads the raw benchmark manifest because the manifest also
contains action-gate metadata that `vlm-eval` does not preserve today:
`expected_action` and `risk_tags`. Invalid gates lower the usable-gate rate and
are never counted as model true negatives.

## Go bigger

Run hosted Cosmos on one fixture scene:

```bash
npa workbench token-factory reason \
  --input-path npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/scenes/warehouse-human-nearby-002 \
  --output-path /tmp/cosmos3-gate/reasoning/warehouse-human-nearby-002 \
  --task "$(cat docs/workbench/guides/assets/cosmos-gated-action-eval/task.txt)" \
  --model nvidia/Cosmos3-Super-Reasoner \
  --max-images 4 \
  --max-tokens 512 \
  --temperature 0.0 \
  --output json
```

Run it over every fixture scene:

```bash
for scene_dir in npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/scenes/*; do
  scene_id="$(basename "$scene_dir")"
  npa workbench token-factory reason \
    --input-path "$scene_dir" \
    --output-path "/tmp/cosmos3-gate/reasoning/$scene_id" \
    --task "$(cat docs/workbench/guides/assets/cosmos-gated-action-eval/task.txt)" \
    --model nvidia/Cosmos3-Super-Reasoner \
    --max-images 4 \
    --max-tokens 512 \
    --temperature 0.0 \
    --output json
done
```

Parse and summarize the live outputs:

```bash
python npa/scripts/report_cosmos_gated_action_eval.py parse \
  --manifest npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/benchmark.json \
  --reasoning-dir /tmp/cosmos3-gate/reasoning \
  --output-jsonl /tmp/cosmos3-gate/parsed/action_gates.jsonl \
  --model nvidia/Cosmos3-Super-Reasoner

python npa/scripts/report_cosmos_gated_action_eval.py summarize \
  --manifest npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/benchmark.json \
  --parsed-gates /tmp/cosmos3-gate/parsed/action_gates.jsonl \
  --vlm-eval-report /tmp/cosmos3-gate-benchmark.json \
  --output-dir /tmp/cosmos3-gate/report \
  --run-id cosmos3-gate-token-factory \
  --result-type measured
```

For cloud handoff, use the same scene layout under object storage and replace
the local paths with placeholders such as:

```bash
npa workbench token-factory reason \
  --input-path s3://<bucket>/<prefix>/scenes/warehouse-human-nearby-002 \
  --output-path s3://<bucket>/<prefix>/reasoning/warehouse-human-nearby-002 \
  --task "$(cat docs/workbench/guides/assets/cosmos-gated-action-eval/task.txt)" \
  --model nvidia/Cosmos3-Super-Reasoner \
  --max-images 4 \
  --max-tokens 512 \
  --temperature 0.0 \
  --output json
```

Use placeholders only in shared docs. Do not paste credential values, signed
URLs, project IDs, or private bucket names into the guide or report.

## Dig deeper

- Fixture manifest:
  `npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/benchmark.json`
- Fixture provenance:
  `npa/src/npa/workbench/vlm_eval/fixtures/cosmos_gated_action_eval/provenance.json`
- Report helper:
  `npa/scripts/report_cosmos_gated_action_eval.py`
- Tests:
  `npa/tests/workbench/test_cosmos_gated_action_eval_fixture.py`
  `npa/tests/workbench/test_cosmos_gated_action_eval_report.py`
