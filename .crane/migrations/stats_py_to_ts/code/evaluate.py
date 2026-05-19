#!/usr/bin/env python3
"""Crane verifier for the stats_py_to_ts example migration.

Prints JSON to stdout with `migration_score` and companion fields. Crane parses
`migration_score` to decide accept/reject; the companion fields are logged in
iteration history and the status comment.

How it works:
  1. Loads the source-side Python stats library and runs the parity corpus
     to produce reference outputs.
  2. Loads the target-side TypeScript+Go implementation (if present) and runs
     the same corpus against it. For each case, compares against the reference
     within a small numerical tolerance.
  3. Runs source-side and target-side test suites if present.
  4. Computes `migration_score = correctness_gate * progress`.

The target side is invoked through a tiny driver script the migration agent is
expected to create at `code/target/ts/run_case.{js,mjs}` (or compiled to a
runnable form). Until that driver exists, every parity case fails to run and
the migration sits at progress=0 — which is the correct starting state for the
first iteration's plan.

Crane should NOT modify this script after iteration 1. The evaluator is the
scoreboard; changing it mid-flight invalidates all prior iterations.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(HERE, "source", "python_stats")
TARGET_DIR = os.path.join(HERE, "target", "ts")
PARITY_FILE = os.path.join(HERE, "parity", "cases.json")

# Numerical tolerance for float comparison on the parity corpus.
ABS_TOL = 1e-9
REL_TOL = 1e-9


def _load_source_module():
    """Load `python_stats/__init__.py` as a module without polluting sys.path."""
    init_path = os.path.join(SOURCE_DIR, "__init__.py")
    spec = importlib.util.spec_from_file_location("python_stats", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["python_stats"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare numeric values or tuples/lists of them within tolerance."""
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return False
        return all(_values_match(e, a) for e, a in zip(expected, actual))
    try:
        ef = float(expected)
        af = float(actual)
    except (TypeError, ValueError):
        return expected == actual
    return math.isclose(ef, af, abs_tol=ABS_TOL, rel_tol=REL_TOL)


def _load_cases() -> List[Dict[str, Any]]:
    with open(PARITY_FILE) as f:
        return json.load(f)


def _run_source_cases(source_mod, cases: List[Dict[str, Any]]) -> List[Any]:
    """Run every case through the source-side Python implementation."""
    outputs = []
    for case in cases:
        fn = getattr(source_mod, case["function"])
        outputs.append(fn(*case["args"]))
    return outputs


def _find_target_driver() -> Tuple[str, List[str]] | Tuple[None, None]:
    """Find the target-side driver script the agent is expected to provide.

    The driver reads one parity case as JSON on stdin and prints the result as
    JSON on stdout. Crane is free to implement it in any way that works at
    invocation time — a Node script, a Bun script, or a compiled binary.
    """
    candidates = [
        ("node", [os.path.join(TARGET_DIR, "run_case.mjs")]),
        ("node", [os.path.join(TARGET_DIR, "run_case.js")]),
        ("bun", [os.path.join(TARGET_DIR, "run_case.ts")]),
    ]
    for cmd, args in candidates:
        if os.path.isfile(args[0]):
            return cmd, args
    return None, None


def _run_target_cases(cases: List[Dict[str, Any]]) -> Tuple[List[Any], List[bool]]:
    """Run every case through the target-side driver. Returns (outputs, ran_ok).

    `ran_ok[i]` is True if the driver returned valid JSON for case i — not
    whether the output matched the source. Comparison happens separately.
    """
    cmd, args = _find_target_driver()
    if cmd is None:
        return [None] * len(cases), [False] * len(cases)
    outputs: List[Any] = []
    ran_ok: List[bool] = []
    for case in cases:
        try:
            proc = subprocess.run(
                [cmd, *args],
                input=json.dumps(case),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                outputs.append(None)
                ran_ok.append(False)
                continue
            outputs.append(json.loads(proc.stdout.strip()))
            ran_ok.append(True)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            outputs.append(None)
            ran_ok.append(False)
    return outputs, ran_ok


def _run_source_tests() -> bool:
    """Source-side tests: the source library is small enough that we trust the
    import-and-corpus check as the source-side "test". Returns True if the source
    module imports cleanly and produces results for every parity case.
    """
    try:
        mod = _load_source_module()
        cases = _load_cases()
        _run_source_cases(mod, cases)
        return True
    except Exception:
        return False


def _run_target_tests() -> bool:
    """Target-side tests: run `npm test` or `bun test` in the target directory
    if a package.json exists. Returns True if the command succeeds or if no
    target side has been set up yet (the migration is allowed to start with
    no target tests; tests should appear by the first porting milestone).
    """
    pkg = os.path.join(TARGET_DIR, "package.json")
    if not os.path.isfile(pkg):
        return True  # nothing to test yet; not a failure
    for cmd in (["bun", "test"], ["npm", "test", "--silent"]):
        try:
            proc = subprocess.run(
                cmd, cwd=TARGET_DIR, capture_output=True, text=True, timeout=120, check=False
            )
            return proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False  # package.json exists but no runner available


def _per_function_progress(
    cases: List[Dict[str, Any]],
    source_outputs: List[Any],
    target_outputs: List[Any],
    ran_ok: List[bool],
) -> Tuple[float, int, int, Dict[str, Tuple[int, int]]]:
    """A function is "ported" only when *all* its parity cases pass.

    Returns (progress_fraction, parity_passing, parity_total, per_fn_breakdown).
    """
    by_fn: Dict[str, List[bool]] = {}
    for case, src, tgt, ok in zip(cases, source_outputs, target_outputs, ran_ok):
        passed = ok and _values_match(src, tgt)
        by_fn.setdefault(case["function"], []).append(passed)
    fn_breakdown: Dict[str, Tuple[int, int]] = {
        fn: (sum(results), len(results)) for fn, results in by_fn.items()
    }
    fns_done = sum(1 for results in by_fn.values() if all(results))
    fns_total = len(by_fn)
    progress = (fns_done / fns_total) if fns_total > 0 else 0.0
    parity_passing = sum(1 for r in (ok and _values_match(s, t)
                                     for s, t, ok in zip(source_outputs, target_outputs, ran_ok))
                         if r)
    parity_total = len(cases)
    return progress, parity_passing, parity_total, fn_breakdown


def main() -> int:
    source_tests_passing = _run_source_tests()
    if source_tests_passing:
        source_mod = _load_source_module()
        cases = _load_cases()
        source_outputs = _run_source_cases(source_mod, cases)
    else:
        cases = []
        source_outputs = []

    target_outputs, ran_ok = _run_target_cases(cases) if cases else ([], [])
    target_tests_passing = _run_target_tests()
    progress, parity_passing, parity_total, by_fn = _per_function_progress(
        cases, source_outputs, target_outputs, ran_ok
    )

    correctness_gate = (
        1.0
        if (source_tests_passing and target_tests_passing and parity_passing == parity_total and parity_total > 0)
        else 0.0
    )
    migration_score = correctness_gate * progress

    print(json.dumps({
        "migration_score": round(migration_score, 6),
        "progress": round(progress, 6),
        "source_tests_passing": source_tests_passing,
        "target_tests_passing": target_tests_passing,
        "parity_passing": parity_passing,
        "parity_total": parity_total,
        "per_function": {fn: {"passing": p, "total": t} for fn, (p, t) in by_fn.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
