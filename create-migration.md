# Creating Crane Migrations

This prompt guides you, a coding agent, to create a new **Crane migration** — a planned, verified port of code from one language (or runtime) to another, executed iteratively on a schedule.

## What is a Crane Migration?

Crane is a GitHub Agentic Workflow that runs code migrations. Each migration is defined by a **directory** under `.crane/migrations/`, a **markdown file** in `.crane/migrations/`, or a **GitHub issue** with the `crane-migration` label.

### Directory-based migrations (preferred when there's an evaluator or parity corpus)

```
.crane/migrations/<migration-name>/
├── migration.md             ← definition (Source, Target, Strategy, Verification)
└── code/                    ← evaluator, parity corpus, supporting fixtures
    ├── evaluate.py          ← outputs the JSON health score
    ├── parity/              ← input/expected pairs the evaluator runs against
    └── ...
```

### Bare-markdown migrations (when verification is just `make test`)

```
.crane/migrations/<migration-name>.md
```

A repository can have multiple migrations running independently — Python → TypeScript on one slice of the codebase, CommonJS → ESM on another, Flask → FastAPI on a third. Each gets its own schedule, plan, long-running branch (`crane/<migration-name>`), and draft PR.

## Step 1: Understand the Repository

Before defining a migration, understand what you're starting from:

1. Read `README.md`, `AGENTS.md`, and `CLAUDE.md` (if they exist).
2. Identify the source language(s), version(s), and runtime.
3. Check the build/test setup — what commands does CI run? How long do they take?
4. Check for existing migrations in `.crane/migrations/` to avoid overlap.
5. Map the rough module structure of the source. Are there obvious seams?
6. Check test coverage. If there's no test suite, the first milestone will be "characterize behavior" — not a porting task — and the user should know that.

## Step 2: Choose Source, Target, and Strategy

### Source

Pick a **bounded** slice of the codebase. A migration that says "port the whole monorepo" will thrash; one that says "port `packages/stats`" will finish. You can run several migrations in parallel covering different slices.

### Target

The target can be a single language or multiple languages with clear roles. Common patterns:

- **Pure swap** — Python → TypeScript, end to end.
- **Polyglot core** — TypeScript at the surface, Go or Rust for hot paths called via WASM, native add-on, or subprocess. The migration definition lists both targets and assigns each piece of code a primary target.
- **Runtime upgrade** — Same language, new runtime (Python 2 → 3, CommonJS → ESM, Node → Bun).

### Strategy: in-place or greenfield

- **`in-place`** — Strangler-fig pattern: the system stays live throughout. Each milestone ports one unit and re-routes its callers to the new implementation, deleting the old code in the same change. There is always a working build. Recommended whenever the system has external consumers, is in production, or is large.
- **`greenfield`** — Build the target in parallel in a separate path. Milestones port units and prove parity against the source on a corpus. Cutover happens once parity is total. Use when the source is small and self-contained, or when interleaving is impractical (e.g. the source is impossible to refactor safely).
- **`auto`** — Let Crane decide on the first iteration based on the inventory. This is the safe default unless you have a strong opinion.

A good Crane migration has these properties:

- **Verifiable**: There's a command that prints a JSON health score, and the score combines correctness (tests pass, behavior matches) with progress (how much has been ported).
- **Bounded scope**: The source paths are well-defined; out-of-scope files are off-limits.
- **Decomposable**: The source can be broken into milestones that each fit in one iteration.
- **Reversible per step**: A bad iteration can be discarded without leaving the system broken.

## Step 3: Choose a Layout

**Prefer issue-based migrations when verification is simple** (e.g. `npm test`). They're easiest to create, monitor, and steer.

- **Issue-based** (GitHub issue with `crane-migration` label) — fastest to start. Open an issue, fill in the template, the workflow picks it up. Steer by commenting on the issue.
- **Directory-based** (`.crane/migrations/<name>/`) — best when you need a parity corpus, a custom evaluator script, or staging directories for the migration in progress.
- **Bare-markdown** (`.crane/migrations/<name>.md`) — when the migration modifies existing repo code and verification is just an existing repo command.

If unclear which layout fits, **ask the user**.

## Step 4: Write the Migration File

The migration file (`migration.md` or `<name>.md`) defines four things:

1. **Source** — language, version, runtime, paths
2. **Target** — language(s), runtime, paths (multiple targets allowed, e.g. TypeScript + Go core)
3. **Strategy** — `in-place`, `greenfield`, or `auto`
4. **Verification** — command that prints JSON with `migration_score` (0.0–1.0) and optionally companion fields

### Frontmatter

```yaml
---
schedule: every 6h            # Options: every Nh, every Nm, daily, weekly
timeout-minutes: 45           # Optional
strategy: auto                # in-place | greenfield | auto
source-language: python
target-languages: [typescript, go]   # one or more
target-metric: 1.0            # The migration is complete when health score reaches this
metric_direction: higher      # higher is better (default)
---
```

`target-metric: 1.0` is the typical "completed when fully migrated and verified" setting. Omitting it makes the migration open-ended (Crane will keep polishing forever).

### Verification output

The verification command must print JSON. The required field is `migration_score` (0.0–1.0). Other fields are optional but recommended — Crane logs them in the iteration history and uses them in the status comment.

```json
{
  "migration_score": 0.42,
  "progress": 0.55,
  "source_tests_passing": true,
  "target_tests_passing": true,
  "parity_passing": 18,
  "parity_total": 32,
  "perf_ratio": 1.4
}
```

**Recommended convention for `migration_score`:**

```
migration_score = correctness_gate × progress
```

where `correctness_gate` is `1.0` only when **all** of `source_tests_passing`, `target_tests_passing`, and `parity_passing == parity_total` are true (otherwise `0.0`), and `progress` is the fraction of the source that has been ported and verified. This produces a clean ratchet: any regression in correctness drops the score to zero and the iteration is rejected; partial progress is rewarded; only a fully migrated, fully passing system reaches `1.0`.

### Body sections

```markdown
# <Migration Name>

## Source

- **Language**: Python 3.11
- **Runtime**: CPython
- **Paths**:
  - `src/stats/` — the library being migrated
  - `tests/stats/` — existing test suite (kept until target tests cover the same surface)

## Target

- **Languages**: TypeScript (primary), Go (hot-path core)
- **Runtime**: Node 22 / Bun 1.x
- **Paths**:
  - `src/stats-ts/` — TypeScript surface
  - `src/stats-ts/native/` — Go core compiled to WASM
- **Bridge**: Go core exposed as WASM, called from TypeScript through a thin wrapper. Hot paths only — the rest stays pure TypeScript.

## Strategy

`in-place` (strangler-fig). Each function is ported one at a time. The Python implementation stays until the TypeScript+Go path passes the parity corpus for that function, then it's deleted in the same commit.

## Verification

```bash
.crane/migrations/<name>/code/evaluate.py
```

The metric is `migration_score`. **Higher is better.** The script runs the source-side test suite, the target-side test suite, and a 200-case parity corpus, and prints the combined JSON.

## Out of scope

- `src/cli/` — CLI tool stays in Python
- `src/migrations/` — database migrations are not touched
```

## Step 5: Validate

1. Run the verification command locally and check the JSON output.
2. Verify the source and target paths exist (or, for greenfield targets, the parent directory exists).
3. Ensure no `<!-- CRANE:UNCONFIGURED -->`, `REPLACE`, or `TODO` placeholders remain.
4. Ensure the migration name is unique.

## Running Manually

- **Slash command**: `/crane <migration-name>: <optional instructions>`
- **Workflow dispatch**: Trigger from the Actions tab. Use the optional `migration` input to run a specific migration by name (bypasses scheduling).
- **CLI**: `gh aw run crane` or `gh aw run crane --inputs migration=<migration-name>`

## Creating a Migration from an Issue

The quickest way:

1. Open a new issue using the **Crane Migration** issue template (or create one manually with the `crane-migration` label).
2. Fill in Source, Target, Strategy, and Verification — the format matches `migration.md`.
3. The next scheduled run discovers the issue and includes it in scheduling.
4. A status comment is posted/updated on the issue after each run.
5. Per-iteration comments are posted with the Actions run link and a summary of what happened.
6. Steer the migration by commenting on the issue — the agent reads new comments before each iteration.
