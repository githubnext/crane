---
name: Crane Migration
about: Create a new Crane code-migration
title: ''
labels: crane-migration
---

<!-- CRANE:ISSUE-MIGRATION -->
<!-- This issue defines a Crane migration. The format is identical to migration.md files. -->
<!-- Crane will discover this issue by its label and run iterations automatically. -->
<!-- After each run, a status comment will be posted/updated with links and results. -->

---
schedule: every 6h
strategy: auto                   # in-place | greenfield | auto
source-language: REPLACE         # e.g. python, ruby, perl
target-languages: [REPLACE]      # e.g. [typescript], [typescript, go], [kotlin]
target-metric: 1.0               # migration is complete when health score reaches this
metric_direction: higher
---

# Migration Name

## Source

<!-- What you're migrating from. Be specific about language version, runtime, and paths. -->

- **Language**: REPLACE (e.g. Python 3.11)
- **Runtime**: REPLACE (e.g. CPython)
- **Paths**:
  - `REPLACE/path/to/source` — (what lives here)
  - `REPLACE/path/to/source-tests` — existing test suite

## Target

<!-- What you're migrating to. Multiple target languages are allowed (e.g. TypeScript with a Go core for hot paths). -->

- **Languages**: REPLACE (e.g. TypeScript, Go)
- **Runtime**: REPLACE (e.g. Node 22 / Bun 1.x)
- **Paths**:
  - `REPLACE/path/to/target` — (what should live here)
- **Bridge** *(if polyglot)*: REPLACE (e.g. "Go core compiled to WASM, called from TypeScript through a thin wrapper")

## Strategy

<!-- Choose one and justify, or leave as `auto` in the frontmatter and let Crane decide on its first iteration. -->

REPLACE — explain why this strategy fits.

- `in-place` (strangler-fig): system stays live throughout. Each milestone ports one unit and re-routes callers. Preferred for production code or anything with external consumers.
- `greenfield`: target built in parallel; cutover after parity is total. Best for small, self-contained sources.
- `auto`: let Crane pick on first iteration.

## Verification

<!-- A command that prints JSON containing `migration_score` (0.0–1.0). Recommended: migration_score = correctness_gate × progress -->

```bash
REPLACE_WITH_YOUR_VERIFICATION_COMMAND
```

The metric is `migration_score` (0.0–1.0). **Higher is better.** Optional companion fields: `progress`, `parity_passing`, `parity_total`, `source_tests_passing`, `target_tests_passing`, `perf_ratio`.

## Out of scope

<!-- Files Crane must NOT touch. -->

- (list paths that are off-limits even if they share a parent with source/target paths)
