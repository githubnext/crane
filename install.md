# Install Crane

This prompt guides you, a coding agent, to install **Crane** — an automated code-migration platform that runs planned, verified migrations from one language to another on [GitHub Agentic Workflows](https://github.github.com/gh-aw/).

## Your Task

Set up Crane in this repository by:

1. Installing the gh-aw CLI extension
2. Initializing the repo for agentic workflows
3. Copying the Crane workflow and configuration files
4. Compiling the workflows
5. Creating a branch, committing, and opening a pull request
6. Helping create the first Crane migration

## Step 1: Install gh-aw CLI Extension

Install the gh-aw extension directly via the GitHub CLI:

```bash
gh extension install github/gh-aw
```

<details>
<summary>Alternative: install via shell script</summary>

If `gh extension install` is unavailable, download and run the installation script manually:

```bash
curl -fL https://raw.githubusercontent.com/github/gh-aw/main/install-gh-aw.sh -o /tmp/install-gh-aw.sh
bash /tmp/install-gh-aw.sh
rm -f /tmp/install-gh-aw.sh
```

</details>

**Verify installation**:

```bash
gh aw version
```

You should see version information displayed. If you encounter an error, check that:

- GitHub CLI (`gh`) is installed and authenticated
- The installation completed without errors

## Step 2: Initialize Repository for Agentic Workflows

```bash
gh aw init
```

**What this does**: Configures `.gitattributes`, creates the dispatcher agent, and sets up Copilot setup steps.

## Step 3: Clone Crane and Copy Files

Clone the Crane repository and copy its files into this repo:

```bash
git clone https://github.com/githubnext/crane /tmp/crane
```

Copy the workflow definitions:

```bash
cp -r /tmp/crane/workflows/ .github/workflows/
```

Copy the issue template and create the Crane directories:

```bash
mkdir -p .github/ISSUE_TEMPLATE
cp -r /tmp/crane/.github/ISSUE_TEMPLATE/ .github/ISSUE_TEMPLATE/
mkdir -p .crane/migrations
```

Clean up:

```bash
rm -rf /tmp/crane
```

## Step 4: Compile the Workflows

```bash
gh aw compile crane
```

**What this does**: Generates `.github/workflows/crane.lock.yml` from the workflow definition.

## Step 5: Create a Branch, Commit, and Open a Pull Request

Create a new branch for the installation changes, commit, and push:

```bash
git checkout -b install-crane
git add .
git commit -m "Install Crane"
git push -u origin install-crane
```

Then open a pull request for review:

```bash
gh pr create --title "Install Crane" --body "Set up Crane workflows and configuration"
```

Report the pull request link to the user.

## Step 6: Create Your First Migration

Next, suggest to the user that you define their first migration together. The migration will be added to the existing install PR. If they decline, you're done. Otherwise, continue.

Before proposing a migration, **read the repository**:

- What language(s) is the existing code in? What versions?
- What does the build/test setup look like? Is there CI?
- How big is the codebase? Roughly how many modules?
- Are there obvious seams (a `core/` directory, a service boundary, a routing layer)?
- Are there clear pain points — slow paths, unmaintainable areas, outdated runtimes?
- Will the target stack require new build-system scaffolding that does not exist yet (for example, adding Go tooling to a TypeScript project)?
- What deterministic CI checks must be green before a migration can be called complete? Identify the exact command, workflow job, or check-run name that will prove cutover/deletion readiness on the Crane PR head.

Then ask the user the questions every migration needs:

1. **From what to what?** Source language(s) and version(s), target language(s) and runtime. A migration can have multiple target languages — e.g. TypeScript with a Go core for hot paths.
2. **How often should the stepwise migrator run?** Choose a per-migration cadence such as `every 1h`, `every 6h`, `daily`, or `weekly`. Consider migration complexity, how often the team can review changes, and risk tolerance. Use this as the migration's `schedule:` value.
3. **Repo/setup scenario.** Is this an existing repo being migrated in place, a new repo for a new version in a different language, a hot-swap where old and new implementations coexist during cutover, or something else?
4. **API and boundary plan.** Should existing public APIs stay in the current language while only hot loops or selected components move, or is the entire project moving to the new language? If only part of the project moves, identify the bridge boundary (FFI, WASM, subprocess, HTTP, package boundary, etc.).
5. **Strategy: in-place or greenfield?** Default to `auto` and let Crane decide on its first run unless the user has a strong preference.
   - **In-place (strangler-fig)** keeps the system live throughout — recommended for anything in production or with external consumers.
   - **Greenfield** rebuilds in parallel and cuts over — only choose this when the source is small, self-contained, and you can afford a cutover window.
6. **Source and target paths.** Where does the source live now, and where should the migrated code land? For polyglot targets, list a path per target language.
7. **Verification.** How do we know the migration is still working after each step? Typically: existing test suite passes, plus a parity check on a corpus of inputs. If there's no test suite, that's milestone zero — Crane should land one before migrating anything.
8. **Deterministic completion gate.** What proves the migration is actually done, not just locally improved? Define the final gate as a deterministic command or CI check that runs on the Crane PR head and fails unless the system is cutover-ready. It should cover, as applicable: all source and target tests, parity/golden fixture corpus, public API or CLI compatibility, source-code deletion or routing through the target implementation, benchmark/performance bounds, and zero approved exceptions. The migration must not mark `Completed: true` from `migration_score` alone.

Before creating the migration, make the completion gate real:

- If the repository already has a suitable required CI check, name it in the migration's Verification/Completion Gate section and make sure the verification command's `migration_score` can reach `1.0` only when that check's underlying conditions are satisfied.
- If the repository does not have a suitable gate, add a migration milestone before code migration begins to build it. For directory-based migrations, this usually means adding or updating the evaluator, parity/golden fixtures, and a CI job that runs the evaluator. For bare-markdown or issue-based migrations, this usually means adding a test/check command to the repo CI and referencing that check explicitly.
- Ensure `target-metric: 1.0` is paired with this deterministic gate. Reaching the target metric should create a completion candidate; final completion happens only after the current Crane PR head has terminal-success checks.

If the answers imply a new target build system, add an explicit milestone before code migration begins to scaffold and verify that build system. That milestone might include `go.mod`, toolchain setup, package scripts, CI updates, and a smoke test.

This applies both to greenfield rewrites and to partial migrations such as moving hot loops into Go or Rust while keeping the existing API surface in TypeScript, Python, or another current language.

Help the user create the migration as a GitHub issue using the **Crane Migration** issue template. See [`create-migration.md`](create-migration.md) for a detailed guide.

A good first migration has:

- A **bounded** source — a single library, service, or module, not the whole monorepo at once
- An **executable verification** — tests that already pass before the migration starts
- A **clear seam** — at least one place where the target language can take over without breaking the rest of the system

If the source has no tests, the user should know that the first iteration will likely be "characterize behavior" (write parity tests against the existing implementation), not actual porting. That's normal and necessary.

## Troubleshooting

### gh aw not found

- Verify GitHub CLI is installed: `gh --version`
- Re-run the installation command from Step 1
- Check that `gh auth status` shows a valid session

### Compile fails

- Ensure `.github/workflows/crane.md` exists
- Ensure `.github/workflows/shared/` and `.github/workflows/scripts/` directories were copied
- Re-run `gh aw compile crane` with `--verbose` for details

## Reference

- **Crane repository**: https://github.com/githubnext/crane
- **GitHub Agentic Workflows**: https://github.github.com/gh-aw/
- **Creating migrations**: See `create-migration.md`
