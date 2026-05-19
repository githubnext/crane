---
schedule: every 6h
strategy: in-place
source-language: python
target-languages: [typescript, go]
target-metric: 1.0
metric_direction: higher
---

# Stats: Python → TypeScript with a Go core

## Source

- **Language**: Python 3.11
- **Runtime**: CPython
- **Paths**:
  - `.crane/migrations/stats_py_to_ts/code/source/python_stats/` — the small statistics library being migrated
  - `.crane/migrations/stats_py_to_ts/code/parity/` — parity corpus (input/expected pairs) — *fixtures only, the evaluator owns this*

## Target

- **Languages**: TypeScript (primary), Go (hot-path core)
- **Runtime**: Node 22 / Bun 1.x
- **Paths**:
  - `.crane/migrations/stats_py_to_ts/code/target/ts/` — TypeScript surface
  - `.crane/migrations/stats_py_to_ts/code/target/ts/native/` — Go core compiled to WASM
- **Bridge**: The Go core is compiled to WASM and called from TypeScript through a thin wrapper. Only the numerically heavy reductions (`mean`, `variance`, `quantile`, `linear_regression`) cross into Go; everything else stays pure TypeScript.

## Strategy

**`in-place` (strangler-fig).** Each function is ported one at a time. The Python implementation stays in place until the TypeScript+Go path passes the parity corpus for that function, then it is deleted in the same commit that flips callers over to the new implementation.

Why in-place: the Python library has external consumers (other migrations and example code), the parity corpus has clear per-function inputs/outputs, and the goal is a smooth handoff with no cutover event.

## Verification

```bash
python3 .crane/migrations/stats_py_to_ts/code/evaluate.py
```

The metric is `migration_score` (0.0–1.0). **Higher is better.**

Companion fields produced by the evaluator:
- `progress` — fraction of source functions whose TypeScript+Go path passes parity
- `source_tests_passing` — Python source-side tests still pass (bool)
- `target_tests_passing` — TypeScript target-side tests pass (bool)
- `parity_passing` / `parity_total` — corpus cases passing / total cases
- `perf_ratio` — geometric mean of (Python time / TypeScript+Go time) across hot-path cases; higher means the new path is faster

The score formula:

```
correctness_gate = 1.0 if (source_tests_passing AND target_tests_passing AND parity_passing == parity_total) else 0.0
migration_score  = correctness_gate * progress
```

This makes `migration_score` a strict ratchet — any correctness regression collapses it to zero and the iteration is rejected.

## Out of scope

- `.crane/migrations/stats_py_to_ts/code/evaluate.py` — the evaluator itself is sacred after iteration 1
- Any path outside `.crane/migrations/stats_py_to_ts/code/`
