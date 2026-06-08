# Crane

<img src="assets/icon.png" width="100" align="left" style="margin-right: 16px;">

Crane automates **code migration between languages**. Describe what you're moving from and to in a single GitHub issue or markdown file, and Crane plans the migration, executes it piece by piece on a schedule, verifies that the system still works after every step, and keeps only changes that preserve behavior.

<br clear="left">

Crane runs on [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/) and [GitHub Copilot](https://github.com/features/copilot). It is a sibling project to [autoloop](https://github.com/githubnext/autoloop), specialized for migrations rather than open-ended optimization.

## Quick start

Paste this into your favorite coding agent session on the repo you want to migrate:

```
Install crane using https://github.com/githubnext/crane/blob/main/install.md
```

The agent will install [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/) if needed, set up the Crane workflows, and walk you through defining your first migration.

To add another migration later, paste this:

```
Create a new crane migration using https://github.com/githubnext/crane/blob/main/create-migration.md
```

## How it works

You create a **migration** — either as a GitHub issue (using the included issue template) or a file in your repo — that defines:

1. **Source** — the language, runtime, and paths you're migrating *from*
2. **Target** — the language(s), runtime, and paths you're migrating *to* (a migration can have multiple target languages, e.g. TypeScript with a Go core for hot paths)
3. **Strategy** — `in-place` (strangler-fig: swap module by module while keeping the system live) or `greenfield` (parallel rewrite), or `auto` to let Crane pick
4. **Verification** — a command that outputs a JSON health score combining correctness (tests pass, behavior matches) with progress (how much has been migrated)
5. **Completion Gate** — deterministic CI or check-run evidence on the Crane PR head before the migration can be marked complete

Crane does the rest. On its **first run** for a migration, it inventories the source, decides a strategy if you left it on `auto`, and writes a living **plan** broken into milestones. On every scheduled run after that:

1. Picks the most-overdue migration
2. Reads the migration definition, the current plan, and the iteration history
3. Picks the next milestone — usually one module, one boundary, or one slice of behavior
4. Implements the migration step in place, with whatever bridges or shims are needed to keep the system working
5. Runs the verification command and checks that the new health score is at least as good as the previous one (any regression is rejected)
6. If verification passes and CI is green: commits to the migration branch, updates the plan to mark the milestone done, advances the draft PR. If not: discards the change, records what went wrong, and tries something different next time.

All state — the plan, milestone status, lessons learned, blockers, iteration history — lives in a per-migration markdown file on a dedicated `memory/crane` branch using [repository memory](https://github.github.com/gh-aw/guides/memoryops/#repository-memory). The plan is human-readable, version-controlled, and editable: browse the `memory/crane` branch to see exactly where the migration stands, or edit the plan file directly to add milestones, retire blockers, or set priorities.

**You stay in control.** Each migration gets its own long-running branch (`crane/<migration-name>`) that you can merge whenever you want. You can steer Crane at any time by commenting on the migration's issue or editing the plan on the memory branch.

### In-place vs greenfield

| | In-place (strangler-fig) | Greenfield |
|---|---|---|
| **System** | Stays live and working throughout | Built up in parallel; cut over when ready |
| **Best when** | The system is in production, large, or has many consumers; you can introduce a bridge (FFI, IPC, HTTP) between languages | The system is small enough to port wholesale, or the source is too tangled to interleave |
| **Risk profile** | Low — every step ships and is verified against real traffic; rollback is one commit | Higher — divergence accumulates until cutover, parity must be proven cold |
| **What a milestone looks like** | "Port module `X` to target, route callers through the new implementation, delete the old one" | "Port module `X`, add parity tests, snapshot diff against the source on the parity corpus" |

Crane picks `in-place` by default for anything that has callers outside the migration scope, and `greenfield` for self-contained projects. You can force either, or leave it as `auto`.

### Scheduling

The workflow runs on a fixed schedule (every 6 hours by default) and runs **one migration per trigger**. Each run, it picks the most-overdue migration — so if you have several active migrations, they take turns. Migrations can set their own `schedule:` in their frontmatter (e.g. `every 1h`, `daily`). To run more migrations more often, increase the workflow's trigger frequency.

## What to use it for

- **Language migrations** — Python → TypeScript, Ruby → Go, JavaScript → TypeScript, Java → Kotlin, Perl → anything, COBOL → anything.
- **Runtime migrations** — CommonJS → ESM, Python 2 → Python 3, Node → Bun/Deno, Webpack → Vite.
- **Polyglot core extractions** — keep most of a TypeScript or Python app, but lift hot paths into Rust/Go/C++ as a native add-on that the rest of the system calls through a stable boundary.
- **Framework migrations** — Express → Fastify, Flask → FastAPI, Rails → Phoenix.

Anything that has a clear *before*, a clear *after*, and a way to verify behavior is preserved is a candidate.

## Example migrations

### `stats_py_to_ts` — Python → TypeScript with a Go core

A small Python statistics library migrated to TypeScript, with the numerically-heavy reductions lifted into a Go add-on called from TypeScript via WASM. In-place strategy: each function is ported one at a time, the Python implementation stays in place until the TypeScript+Go path passes the parity corpus, then it's removed.

- **Verification**: parity score against a 200-case input/expected corpus, plus source-side and target-side test suites
- **Code**: [`.crane/migrations/stats_py_to_ts/`](.crane/migrations/stats_py_to_ts/)

### `flask_to_fastapi` (bare markdown)

Strangler-fig migration of a Flask app to FastAPI, route by route. New routes register on FastAPI, old routes proxy to Flask until they're ported.

- **Verification**: `pytest -q && python tools/parity_check.py`
- **Code**: [`.crane/migrations/flask_to_fastapi.md`](.crane/migrations/flask_to_fastapi.md)

## Adding a new migration

Most migrations are **goal-oriented**: you want to finish. Set `target-metric: 1.0` (the default convention is `migration_score`, where 1.0 means fully ported and all verification passes). Reaching that score creates a completion candidate; Crane marks the migration complete only after the current Crane PR head has deterministic terminal-success checks. Open-ended migrations are unusual but legal — leave `target-metric` off and Crane keeps polishing forever.

### Option A: From a GitHub issue (quickest)

1. Open a new issue using the **Crane Migration** template (or manually apply the `crane-migration` label)
2. Fill in Source, Target, Strategy, Verification, and Completion Gate in the issue body
3. The next scheduled run picks it up automatically
4. Monitor progress via the status comment and per-run comments on the issue
5. Steer the migration by commenting on the issue — the agent reads new comments before each iteration

### Option B: From a directory (preferred when there's a parity corpus or eval harness)

1. Create a directory under `.crane/migrations/`:
   ```
   .crane/migrations/my-migration/
   ├── migration.md
   └── code/
       ├── parity/           ← inputs and expected outputs
       ├── evaluate.py       ← computes the health score
       └── ...
   ```

2. Define Source, Target, Strategy, Verification, and Completion Gate in `migration.md`.

3. The next scheduled run picks it up automatically.

See [`create-migration.md`](create-migration.md) for a detailed guide.

## Slash command

Crane registers a `/crane` slash command. Use it from any GitHub issue or PR comment.

**Syntax:**

```
/crane [<migration-name>:] <instructions>
```

**Examples:**

| Command | What happens |
|---|---|
| `/crane` | Runs the next scheduled iteration (or asks which migration if more than one is active) |
| `/crane stats_py_to_ts: port the `quantile` family next` | Runs one iteration of `stats_py_to_ts` focused on those functions |
| `/crane switch the strategy to greenfield` | Updates the active migration's strategy and confirms |
| `/crane mark milestone "tokenizer" done` | Updates the plan and commits the change |

If a migration name is given before the colon it must match a directory in `.crane/migrations/` or a GitHub issue with the `crane-migration` label. If no name is given and only one migration is active, that one is used.

## Repository structure

```
crane/
├── workflows/                         ← Agentic Workflow definitions
│   ├── crane.md                       ← the workflow (compiled by gh aw)
│   ├── shared/reporting.md
│   └── scripts/crane_scheduler.py     ← scheduler
├── .crane/
│   └── migrations/                    ← example migrations
│       ├── stats_py_to_ts/
│       │   ├── migration.md           ← source, target, strategy, verification
│       │   └── code/                  ← evaluator, parity corpus, source/target trees
│       └── flask_to_fastapi.md        ← bare-markdown migration
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── crane-migration.md
    └── workflows/                     ← compiled lock file (generated)
```

Migrations are **self-contained**. Directory-based migrations carry their evaluator and parity corpus alongside the definition. Bare-markdown migrations modify existing repo code and use a verification command that already exists in the repo (e.g. `make test`). Issue-based migrations use the same format as `migration.md` and are discovered via the `crane-migration` label.

## How the planning loop works

Crane treats planning as a first-class step:

1. **Inventory** — On the first iteration for a migration, Crane scans the source paths, builds a module/dependency graph, identifies seams (places where you can cleanly cut between modules), and surfaces risk areas (modules with no tests, large blast radius, external dependencies).
2. **Strategy** — If you set `strategy: auto`, Crane picks `in-place` or `greenfield` based on the inventory and writes a short rationale into the plan.
3. **Milestones** — The plan breaks the migration into ordered milestones. For `in-place`, each milestone names a unit and how its callers will be re-routed. For `greenfield`, each milestone names a unit and how parity will be proven.
4. **Execution** — Each subsequent iteration picks the next milestone, implements it, verifies, and updates the plan. The plan is a living document — milestones can be split, reordered, retired, or added as Crane learns.
5. **Verification gates** — A milestone is only marked done when (a) source-side tests still pass, (b) target-side tests pass, (c) parity tests (if any) pass, and (d) the migration health score did not regress. Final completion additionally requires deterministic PR-head checks. Anything less and the iteration is rejected or left as a completion candidate.

See [`AGENTS.md`](AGENTS.md) for the full architecture.

## Built on

- [GitHub Agentic Workflows](https://github.com/github/gh-aw) — the orchestration platform
- [GitHub Copilot](https://github.com/features/copilot) — the agent engine
- [autoloop](https://github.com/githubnext/autoloop) — the sibling project Crane forked from; same loop shape, different specialization

## Contributing

We don't accept pull requests for this project. Instead, use a coding agent to write a detailed issue describing the bug or feature request — we'll implement it agentically from there. See [GitHub Agentic Workflows' CONTRIBUTING.md](https://github.com/github/gh-aw/blob/main/CONTRIBUTING.md) for the philosophy.
