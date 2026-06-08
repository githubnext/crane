# Crane

Crane is an automated code-migration platform built on [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/).

It runs planned, verified migrations from one language (or runtime) to another. Each iteration advances a living migration plan by one step, verifies that the system still works, and keeps the change only if correctness is preserved. Crane is a sibling of [autoloop](https://github.com/githubnext/autoloop) — same agentic-loop shape, specialized for migration rather than open-ended optimization.

## Architecture

```
crane/
├── AGENTS.md                           ← you are here
├── workflows/
│   ├── crane.md                        ← main crane workflow (compiled by gh-aw)
│   ├── shared/
│   │   └── reporting.md
│   └── scripts/
│       └── crane_scheduler.py          ← scheduler (see workflows/crane.md)
├── .crane/
│   └── migrations/                     ← migrations (directory-based and bare-markdown)
│       ├── stats_py_to_ts/
│       │   ├── migration.md            ← source, target, strategy, verification
│       │   └── code/                   ← evaluator, parity corpus, source/target staging
│       └── flask_to_fastapi.md
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── crane-migration.md          ← issue template for creating migrations
    └── workflows/                      ← compiled workflow (*.lock.yml, generated)
```

## Key Concepts

### Migrations

A **migration** defines a single port from a source language/runtime to a target. Each migration has:

- **Source**: language, version, runtime, and paths being migrated *from*
- **Target**: language(s), runtime, and paths being migrated *to* (multiple target languages allowed — e.g. TypeScript with a Go core for hot paths)
- **Strategy**: `in-place`, `greenfield`, or `auto`
- **Verification**: a command that outputs a JSON health score combining correctness with progress
- **Completion Gate**: deterministic PR-head CI or check-run evidence required before Crane may mark the migration complete

Migrations can be:

- **Directory-based** (`.crane/migrations/<name>/migration.md`): for migrations with a parity corpus or custom evaluator. Code lives in `code/`. Preferred when verification needs supporting fixtures.
- **Bare-markdown** (`.crane/migrations/<name>.md`): for migrations that modify existing repo code where verification is an existing repo command (e.g. `make test`).
- **Issue-based** (GitHub issue with `crane-migration` label): for migrations created and steered directly from a GitHub issue. The issue body uses the same format as `migration.md`. The issue itself becomes the interface for monitoring and steering.

### The Plan

Crane treats planning as a first-class step. Every migration has a **living plan** stored in its state file on the `memory/crane` branch, with these sections:

- **🗺️ Inventory** — modules in the source, their dependencies, their consumers, their test coverage, their risk
- **🧭 Strategy & Rationale** — `in-place` vs `greenfield` and why
- **🪜 Milestones** — ordered list of units to migrate. Each milestone has a name, scope, status (`todo` / `in-progress` / `done` / `blocked`), and acceptance criteria (what verification it needs to pass to be marked done)
- **🎯 Current Focus** — the one milestone the next iteration will work on
- **📚 Lessons Learned** — what worked, what didn't, accumulated across iterations
- **🚧 Blockers & Foreclosed Approaches** — dead ends with the reasons they failed
- **🔭 Future Work** — ideas surfaced but not yet promoted to milestones

The plan is generated on the **first iteration** (inventory + strategy + initial milestone list) and revised on every subsequent iteration. Humans can edit any section directly on the `memory/crane` branch to steer the migration.

### Workflow

The workflow (`workflows/crane.md`) is compiled by `gh aw compile` into `.github/workflows/crane.lock.yml`. It:

1. Runs on a schedule (every 6h by default)
2. Checks which migrations are due (reading state files from repo-memory)
3. Selects the most-overdue migration
4. Runs **one iteration**:
   - **First iteration**: inventory the source, pick a strategy (if `auto`), write the initial plan, commit the plan
   - **Subsequent iterations**: read the plan, pick the next milestone, implement it, verify, accept or reject
5. Commits accepted changes to `crane/<migration-name>`
6. Updates the state file with iteration history, plan changes, and the new health score
7. If the migration has a `target-metric` and the health score reaches it (typically `1.0` for "fully migrated and verified"), records a completion candidate
8. Marks the migration complete only after the current Crane PR head has deterministic terminal-success checks

Branch freshness is handled by the iteration loop: each iteration's branch-setup step fast-forwards or merges `origin/main` into the `crane/*` branch as needed.

### Verification (the Health Score)

Each migration defines a verification command that prints JSON containing `migration_score` — a number in `[0.0, 1.0]` where `1.0` means the migration has reached its target and is ready for the deterministic completion gate.

The recommended convention is:

```
migration_score = correctness_gate × progress
```

where `correctness_gate` is `1.0` only when **all** of source-side tests, target-side tests, and parity tests pass — otherwise `0.0`. This makes the score a strict ratchet: any correctness regression collapses it to zero, and the iteration is rejected.

Verification commands typically also emit companion fields (`progress`, `parity_passing`, `parity_total`, `source_tests_passing`, `target_tests_passing`, `perf_ratio`) that Crane logs in iteration history and status comments. These are not used for the accept/reject decision but make the state file far more useful for humans reviewing progress.

Final completion is stricter than the health score. Crane must not mark `Completed: true` from repo-memory, historical score, or a same-run sandbox result alone. A goal-oriented migration becomes complete only when the current Crane PR head has terminal-success checks for the migration's declared completion gate.

### Strategy: in-place vs greenfield

- **`in-place`** (strangler-fig) — the system stays live throughout. Each milestone ports one unit, re-routes its callers through the new implementation (via a bridge — FFI, WASM, native add-on, or just imports in the same project), and deletes the old code in the same change. The build is always green; the system is always shippable. Crane prefers this for anything with external consumers, anything in production, or anything large enough that a cutover would be risky.
- **`greenfield`** — the target is built in parallel in separate paths. Each milestone ports a unit and proves parity against the source on a corpus. Cutover is a separate event once parity is total. Crane chooses this when the source is small, self-contained, or impossible to refactor safely in place.
- **`auto`** — Crane picks on its first iteration based on the inventory and writes a short rationale into the plan.

## Reference

- **Agentic Workflows**: https://github.com/github/gh-aw
- **Quick Start**: https://github.github.com/gh-aw/setup/quick-start/
- **Crane Examples**: See the [example migrations](.crane/migrations/) included in this repo
- **Sibling project**: https://github.com/githubnext/autoloop

## Conventions

- Migrations are self-contained: each directory-based migration has everything needed to run its loop (definition, evaluator, parity corpus)
- The agent only modifies files inside the source/target paths declared in the migration's Source and Target sections (plus the migration's own `code/` directory for evaluator/corpus updates if needed)
- **Never modify the verification script after it's defined.** A migration's evaluator is its honest scoreboard — changing it mid-flight invalidates all prior iterations
- Verification commands must output JSON containing `migration_score` (a number)
- Each migration has a single **long-running branch** named `crane/<migration-name>` that accumulates all accepted iterations
- A single **draft PR** per migration is created on the first accepted iteration and accumulates subsequent commits
- A single **migration issue** per migration (`[Crane: <migration-name>]`, labeled `crane-migration`) is the source of truth for the migration — it hosts the status comment, per-iteration comments, and human steering. For issue-based migrations this is the source issue; for file-based migrations it's auto-created on the first run
- All state lives in repo-memory — per-migration state files on the `memory/crane` branch are the single source of truth for scheduling, the plan, history, and lessons
- State files: `<migration-name>.md` on the `memory/crane` branch (Machine State table + Plan + research sections)
- The default branch is automatically merged into all `crane/*` branches whenever it changes
- Issue-based migrations are discovered via the `crane-migration` label; the issue body is the migration definition
- A status comment (marked with `<!-- CRANE:STATUS -->`) is maintained on every migration issue (the earliest bot comment, edited in place each iteration), and a per-iteration comment is posted after each iteration
- Migrations can be **goal-oriented** (run until `target-metric` is reached and deterministic PR-head checks pass — typical, since you want to finish) or **open-ended** (run forever, polishing). When a goal-oriented migration completes, the `crane-migration` label is removed and `crane-completed` is added (for issue-based migrations)
- When proposing a new migration, always confirm the five core questions with the user: source-to-target, strategy, paths, verification, deterministic completion gate

## Adding a New Migration

See `create-migration.md` for a step-by-step guide. In short:

### Option A: Directory-based (preferred when you need a parity corpus or evaluator)

1. Create `.crane/migrations/<name>/` with a `migration.md` and `code/` directory
2. Define Source, Target, Strategy, Verification, and Completion Gate in `migration.md`
3. Add the evaluator script and any parity fixtures to `code/`
4. Test the verification command locally — it should print valid JSON with `migration_score`
5. The next scheduled run picks it up automatically

### Option B: Issue-based (quickest way to start)

1. Open a new issue using the "Crane Migration" issue template
2. Fill in Source, Target, Strategy, Verification, and Completion Gate in the issue body
3. Ensure the `crane-migration` label is applied
4. The next scheduled run picks it up automatically
5. Monitor progress via the status comment and per-run comments on the issue

## Running Manually

- **Slash command**: `/crane [<migration-name>:] <instructions>` — post in any GitHub issue or PR comment. The `crane` workflow picks it up and runs one iteration with the given instructions.
- **Workflow dispatch**: Trigger from the Actions tab. Use the optional `migration` input to run a specific migration by name (bypasses scheduling).
- **CLI**: `gh aw run crane` or `gh aw run crane --inputs migration=<migration-name>`

## Deploying

To deploy the workflow to a repository:

1. Copy `workflows/crane.md` to `.github/workflows/crane.md` in the target repo
2. Copy `workflows/shared/` to `.github/workflows/shared/` in the target repo
3. Copy `workflows/scripts/` to `.github/workflows/scripts/` in the target repo
4. Run `gh aw compile crane` to generate the lock file
5. Copy migration directories to `.crane/migrations/` in the target repo (or open issues with the `crane-migration` label)
6. Commit and push
