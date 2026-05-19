---
schedule: every 6h
strategy: in-place
source-language: python
target-languages: [python]
target-metric: 1.0
metric_direction: higher
---

# Flask → FastAPI

A strangler-fig migration of a Flask app to FastAPI. New routes register on FastAPI; old Flask routes are proxied through FastAPI until each one is ported, at which point the Flask handler is deleted. Same Python, same Python tests, same database — only the web framework changes.

## Source

- **Language**: Python 3.11
- **Runtime**: CPython, Flask 2.x
- **Paths**:
  - `app/` — Flask application package
  - `tests/` — existing pytest suite (kept until target tests cover the same surface)

## Target

- **Languages**: Python 3.11
- **Runtime**: FastAPI + uvicorn
- **Paths**:
  - `app/` — same package; FastAPI routes register alongside Flask routes during migration, then replace them
  - `tests/` — same tests; switched route-by-route from Flask test client to FastAPI test client

## Strategy

`in-place` (strangler-fig). FastAPI is mounted as the WSGI/ASGI entrypoint; for each milestone, one route family is reimplemented on FastAPI, its tests are rewritten against the FastAPI test client, and the Flask handler is deleted in the same commit. The app is always live and the test suite is always passing.

## Verification

```bash
pytest -q tests/ && python tools/parity_check.py --routes-list app/routes.txt
```

The metric is `migration_score`. **Higher is better.**

`tools/parity_check.py` walks every route in `app/routes.txt` and:
- Marks routes whose handler is FastAPI as "ported"
- Hits each route with a representative request and checks the response shape against a snapshot
- Prints JSON: `{"migration_score": ..., "progress": ..., "source_tests_passing": ..., "target_tests_passing": ..., "parity_passing": ..., "parity_total": ...}`

`migration_score = correctness_gate × progress`, where `correctness_gate = 1.0` only when pytest passes AND parity is total.

## Out of scope

- `migrations/` — Alembic migrations are not touched by this migration
- `static/`, `templates/` — Jinja templates stay until a separate frontend migration
- `tools/parity_check.py` — the verifier itself is sacred after iteration 1
