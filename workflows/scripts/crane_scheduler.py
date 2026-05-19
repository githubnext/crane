#!/usr/bin/env python3
"""Crane scheduler.

Decides which Crane migration (if any) is due for an iteration. Reads
migration definitions from ``.crane/migrations/`` (directory- and bare-
markdown-based) and from open GitHub issues labelled ``crane-migration``,
combines them with persisted per-migration scheduling state from the
``memory/crane`` repo-memory branch, and writes the selection to
``/tmp/gh-aw/crane.json`` for the agent step to consume.

Side effects:
    * May bootstrap ``.crane/migrations/example.md`` on first run.
    * May materialise issue-based migration bodies under
      ``/tmp/gh-aw/issue-migrations/``.
    * Always writes ``/tmp/gh-aw/crane.json``.

Exit codes:
    0  - a migration was selected, or there are unconfigured migrations to
         report on (the agent step should run).
    1  - nothing to do this run (no due migrations, no unconfigured
         migrations); the workflow should skip the agent step.

Environment variables:
    GITHUB_TOKEN       - token used to query the issues API.
    GITHUB_REPOSITORY  - ``owner/repo`` slug.
    CRANE_MIGRATION    - optional migration name to force (bypasses
                         scheduling, but unconfigured migrations are still
                         rejected).

This file is the standalone counterpart of the scheduler used by
``workflows/crane.md``. Extracting it keeps the compiled ``run:`` step
small and makes the logic unit-testable.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

MIGRATIONS_DIR = ".crane/migrations"
TEMPLATE_FILE = os.path.join(MIGRATIONS_DIR, "example.md")

# Repo-memory files are cloned to /tmp/gh-aw/repo-memory/{id}/ where {id}
# is derived from the branch-name configured in the tools section
# (memory/crane -> crane).
REPO_MEMORY_DIR = "/tmp/gh-aw/repo-memory/crane"

ISSUE_MIGRATIONS_DIR = "/tmp/gh-aw/issue-migrations"
OUTPUT_DIR = "/tmp/gh-aw"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "crane.json")

# Default repo-memory ``max-file-size`` for state files. Mirrors the value
# configured under ``tools.repo-memory.max-file-size`` in
# ``workflows/crane.md``. Surfaced so the agent prompt can reason about the
# rolling-compaction budget without re-parsing workflow frontmatter.
STATE_FILE_MAX_BYTES = 40960


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def parse_machine_state(content):
    """Parse the ⚙️ Machine State table from a state file. Returns a dict."""
    state = {}
    m = re.search(r"## ⚙️ Machine State.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not m:
        return state
    section = m.group(0)
    for row in re.finditer(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|", section):
        raw_key = row.group(1).strip()
        raw_val = row.group(2).strip()
        if raw_key.lower() in ("field", "---", ":---", ":---:", "---:"):
            continue
        key = raw_key.lower().replace(" ", "_")
        val = None if raw_val in ("—", "-", "") else raw_val
        state[key] = val
    # Coerce types
    for int_field in ("iteration_count", "consecutive_errors"):
        if int_field in state:
            try:
                state[int_field] = int(state[int_field])
            except (ValueError, TypeError):
                state[int_field] = 0
    if "paused" in state:
        state["paused"] = str(state.get("paused", "")).lower() == "true"
    if "completed" in state:
        state["completed"] = str(state.get("completed", "")).lower() == "true"
    # recent_statuses: stored as comma-separated words (e.g. "accepted, rejected, error")
    rs_raw = state.get("recent_statuses") or ""
    if rs_raw:
        state["recent_statuses"] = [s.strip().lower() for s in rs_raw.split(",") if s.strip()]
    else:
        state["recent_statuses"] = []
    return state


def parse_schedule(s):
    """Schedule string to a ``timedelta``; returns ``None`` for invalid input."""
    s = s.strip().lower()
    m = re.match(r"every\s+(\d+)\s*h", s)
    if m:
        return timedelta(hours=int(m.group(1)))
    m = re.match(r"every\s+(\d+)\s*m", s)
    if m:
        return timedelta(minutes=int(m.group(1)))
    if s == "daily":
        return timedelta(hours=24)
    if s == "weekly":
        return timedelta(days=7)
    return None


def get_migration_name(pf):
    """Extract migration name from a migration file path.

    Directory-based: ``.crane/migrations/<name>/migration.md`` -> ``<name>``
    Bare markdown:   ``.crane/migrations/<name>.md`` -> ``<name>``
    Issue-based:     ``/tmp/gh-aw/issue-migrations/<name>.md`` -> ``<name>``
    """
    if pf.endswith("/migration.md"):
        return os.path.basename(os.path.dirname(pf))
    return os.path.splitext(os.path.basename(pf))[0]


def slugify_issue_title(title, number=None):
    """Slugify a GitHub issue title into a migration name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)  # collapse consecutive hyphens
    if not slug:
        slug = "issue-{}".format(number) if number is not None else "issue"
    return slug


def parse_link_header(header):
    """Parse the GitHub API ``Link`` header and return the ``rel="next"`` URL."""
    if not header:
        return None
    for part in header.split(","):
        section = part.strip()
        m = re.match(r'^<([^>]+)>;\s*rel="next"$', section)
        if m:
            return m.group(1)
    return None


def parse_migration_frontmatter(content):
    """Parse YAML frontmatter for ``schedule``, ``target-metric``, ``metric_direction``, and ``strategy``.

    Returns a dict with these keys (any may be ``None``):
        schedule_delta              - timedelta or None
        target_metric               - float or None
        target_metric_invalid       - raw string (if value was invalid)
        metric_direction            - "higher" or "lower" (default "higher")
        metric_direction_invalid    - raw string (if value was invalid)
        strategy                    - "in-place", "greenfield", or "auto" (default "auto")
        strategy_invalid            - raw string (if value was invalid)
    """
    # Strip leading HTML comments before checking (issue-based migrations may have them).
    content_stripped = re.sub(r"^(\s*<!--.*?-->\s*\n)*", "", content, flags=re.DOTALL)
    result = {
        "schedule_delta": None,
        "target_metric": None,
        "target_metric_invalid": None,
        "metric_direction": "higher",
        "metric_direction_invalid": None,
        "strategy": "auto",
        "strategy_invalid": None,
    }
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content_stripped, re.DOTALL)
    if not fm_match:
        return result
    for line in fm_match.group(1).split("\n"):
        stripped = line.strip()
        if stripped.startswith("schedule:"):
            schedule_str = line.split(":", 1)[1].strip()
            result["schedule_delta"] = parse_schedule(schedule_str)
        if stripped.startswith("target-metric:"):
            raw = line.split(":", 1)[1].strip()
            try:
                result["target_metric"] = float(raw)
            except (ValueError, TypeError):
                result["target_metric_invalid"] = raw
        if stripped.startswith("metric_direction:") or stripped.startswith("metric-direction:"):
            raw = line.split(":", 1)[1].strip().strip('"').strip("'").lower()
            if raw in ("higher", "lower"):
                result["metric_direction"] = raw
            else:
                result["metric_direction_invalid"] = raw
        if stripped.startswith("strategy:"):
            raw = line.split(":", 1)[1].strip().strip('"').strip("'").lower()
            if raw in ("in-place", "greenfield", "auto"):
                result["strategy"] = raw
            else:
                result["strategy_invalid"] = raw
    return result


def is_unconfigured(content):
    """Return True if a migration file still contains the unconfigured sentinel
    or any TODO/REPLACE placeholder."""
    if "<!-- CRANE:UNCONFIGURED -->" in content:
        return True
    if re.search(r"\bTODO\b|\bREPLACE", content):
        return True
    return False


def check_skip_conditions(state):
    """Return ``(should_skip, reason)`` based on the migration state."""
    if str(state.get("completed", "")).lower() == "true" or state.get("completed") is True:
        return True, "completed: target metric reached"
    if state.get("paused"):
        return True, "paused: {}".format(state.get("pause_reason", "unknown"))
    recent = state.get("recent_statuses", [])[-5:]
    if len(recent) >= 5 and all(s == "rejected" for s in recent):
        return True, "plateau: 5 consecutive rejections"
    return False, None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def read_migration_state(migration_name, repo_memory_dir=REPO_MEMORY_DIR):
    """Read scheduling state from the repo-memory state file (or ``{}``)."""
    state_file = os.path.join(repo_memory_dir, "{}.md".format(migration_name))
    if not os.path.isfile(state_file):
        print("  {}: no state file found (first run)".format(migration_name))
        return {}
    with open(state_file, encoding="utf-8") as f:
        content = f.read()
    return parse_machine_state(content)


def get_state_file_size(migration_name, repo_memory_dir=REPO_MEMORY_DIR):
    """Return the size of the migration's state file in bytes (0 if missing)."""
    state_file = os.path.join(repo_memory_dir, "{}.md".format(migration_name))
    try:
        st = os.stat(state_file)
    except OSError:
        return 0
    return st.st_size


def _bootstrap_template_if_missing():
    """Create ``.crane/migrations/example.md`` if the directory is missing."""
    if os.path.isdir(MIGRATIONS_DIR):
        return
    os.makedirs(MIGRATIONS_DIR, exist_ok=True)
    bt = chr(96)  # backtick — keep gh-aw compiler happy if this ever gets inlined
    template = "\n".join([
        "<!-- CRANE:UNCONFIGURED -->",
        "<!-- Remove the line above once you have filled in your migration. -->",
        "<!-- Crane will NOT run until you do. -->",
        "",
        "---",
        "schedule: every 6h",
        "strategy: auto",
        "source-language: REPLACE",
        "target-languages: [REPLACE]",
        "target-metric: 1.0",
        "metric_direction: higher",
        "---",
        "",
        "# Crane Migration",
        "",
        "<!-- Rename this file to something meaningful (e.g. stats_py_to_ts.md, cjs_to_esm.md).",
        "     The filename (minus .md) becomes the migration name used in issues, PRs,",
        "     and slash commands. Want multiple migrations? Add more .md files here. -->",
        "",
        "## Source",
        "",
        "- **Language**: REPLACE",
        "- **Runtime**: REPLACE",
        "- **Paths**:",
        "  - {bt}REPLACE/path{bt} -- (what lives here)".format(bt=bt),
        "",
        "## Target",
        "",
        "- **Languages**: REPLACE",
        "- **Runtime**: REPLACE",
        "- **Paths**:",
        "  - {bt}REPLACE/path{bt} -- (what should live here)".format(bt=bt),
        "",
        "## Strategy",
        "",
        "REPLACE -- explain choice (or leave as `auto` in frontmatter and let Crane decide).",
        "",
        "## Verification",
        "",
        "<!-- A command that prints JSON containing `migration_score` (0.0-1.0). -->",
        "",
        "{bt}{bt}{bt}bash".format(bt=bt),
        "REPLACE_WITH_YOUR_VERIFICATION_COMMAND",
        "{bt}{bt}{bt}".format(bt=bt),
        "",
        "The metric is {bt}migration_score{bt}. **Higher is better.**".format(bt=bt),
        "",
    ])
    with open(TEMPLATE_FILE, "w") as f:
        f.write(template)
    # Leave the template unstaged — the agent will create a draft PR with it
    print("BOOTSTRAPPED: created {} locally (agent will create a draft PR)".format(TEMPLATE_FILE))


def _scan_directory_migrations():
    """Return paths of directory-based migrations under ``MIGRATIONS_DIR``."""
    out = []
    if not os.path.isdir(MIGRATIONS_DIR):
        return out
    for entry in sorted(os.listdir(MIGRATIONS_DIR)):
        mig_dir = os.path.join(MIGRATIONS_DIR, entry)
        if os.path.isdir(mig_dir):
            mig_file = os.path.join(mig_dir, "migration.md")
            if os.path.isfile(mig_file):
                out.append(mig_file)
    return out


def _scan_bare_migrations():
    """Return paths of bare-markdown migrations under ``MIGRATIONS_DIR``."""
    return sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.md")))


def _fetch_issue_migrations(repo, github_token):
    """Fetch open issues with the ``crane-migration`` label and write their
    bodies to ``ISSUE_MIGRATIONS_DIR``. Returns ``(migration_files, issue_migrations)``.

    Errors are swallowed (with a warning) so a transient API failure doesn't
    block the run for non-issue-based migrations.
    """
    migration_files = []
    issue_migrations = {}
    os.makedirs(ISSUE_MIGRATIONS_DIR, exist_ok=True)
    next_url = (
        "https://api.github.com/repos/{}/issues"
        "?labels=crane-migration&state=open&per_page=100".format(repo)
    )
    headers = {
        "Authorization": "token {}".format(github_token),
        "Accept": "application/vnd.github.v3+json",
    }
    issues = []
    try:
        while next_url:
            req = urllib.request.Request(next_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = json.loads(resp.read().decode())
                link_header = resp.headers.get("link") or resp.headers.get("Link")
            issues.extend(page)
            next_url = parse_link_header(link_header)
        for issue in issues:
            if issue.get("pull_request"):
                continue  # skip PRs
            body = issue.get("body") or ""
            title = issue.get("title") or ""
            number = issue["number"]
            slug = slugify_issue_title(title, number)
            if slug in issue_migrations:
                print(
                    "  Warning: slug '{}' (issue #{}) collides with issue #{}, "
                    "appending issue number".format(
                        slug, number, issue_migrations[slug]["issue_number"]
                    )
                )
                slug = "{}-{}".format(slug, number)
            issue_file = os.path.join(ISSUE_MIGRATIONS_DIR, "{}.md".format(slug))
            with open(issue_file, "w") as f:
                f.write(body)
            migration_files.append(issue_file)
            issue_migrations[slug] = {"issue_number": number, "file": issue_file, "title": title}
            print("  Found issue-based migration: '{}' (issue #{})".format(slug, number))
    except Exception as e:  # noqa: BLE001 -- best-effort; logged below
        print("  Warning: could not fetch issue-based migrations: {}".format(e))
    return migration_files, issue_migrations


def _parse_target_metric_from_file(path):
    """Re-parse a migration file to extract its ``target-metric``, if any."""
    try:
        with open(path) as f:
            return parse_migration_frontmatter(f.read()).get("target_metric")
    except (OSError, ValueError, TypeError):
        return None


def _parse_metric_direction_from_file(path):
    """Re-parse a migration file to extract its ``metric_direction``."""
    try:
        with open(path) as f:
            return parse_migration_frontmatter(f.read()).get("metric_direction") or "higher"
    except (OSError, ValueError, TypeError):
        return "higher"


def _parse_strategy_from_file(path):
    """Re-parse a migration file to extract its ``strategy``."""
    try:
        with open(path) as f:
            return parse_migration_frontmatter(f.read()).get("strategy") or "auto"
    except (OSError, ValueError, TypeError):
        return "auto"


# ---------------------------------------------------------------------------
# Existing PR lookup (single-PR-per-migration invariant)
# ---------------------------------------------------------------------------


def _http_get_json(url, headers, timeout=30):
    """Open ``url`` and return ``(parsed_body, link_header)``.

    Returns ``(None, None)`` on any HTTP/network error so callers can fall
    through to the next strategy.
    """
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            link_header = resp.headers.get("link") or resp.headers.get("Link")
            return body, link_header
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None, None


def find_existing_pr_for_branch(repo, migration_name, github_token, http_get_json=_http_get_json):
    """Look up the open draft PR (if any) for ``crane/{migration_name}``."""
    if not repo or not migration_name or not github_token:
        return None
    owner = repo.split("/", 1)[0]
    canonical_branch = "crane/{}".format(migration_name)
    headers = {
        "Authorization": "token {}".format(github_token),
        "Accept": "application/vnd.github.v3+json",
    }
    # Strategy 1: exact canonical branch name via the head= filter.
    head_q = urllib.parse.quote("{}:{}".format(owner, canonical_branch), safe="")
    url = "https://api.github.com/repos/{}/pulls?head={}&state=open".format(repo, head_q)
    body, _ = http_get_json(url, headers)
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict) and first.get("number"):
            return first["number"]

    # Strategy 2: paginate open PRs and match either a legacy framework-suffixed
    # branch (``crane/{name}-<6-40 hex>``) or a ``[Crane: {name}]`` title prefix.
    suffix_regex = re.compile(
        r"^crane/" + re.escape(migration_name) + r"(-[0-9a-f]{6,40})?$"
    )
    title_prefix = "[Crane: {}]".format(migration_name)
    next_url = "https://api.github.com/repos/{}/pulls?state=open&per_page=100".format(repo)
    while next_url:
        body, link_header = http_get_json(next_url, headers)
        if not isinstance(body, list):
            break
        for pr in body:
            if not isinstance(pr, dict):
                continue
            head_ref = ""
            head = pr.get("head") or {}
            if isinstance(head, dict):
                head_ref = head.get("ref") or ""
            if suffix_regex.match(head_ref):
                return pr.get("number")
            title = pr.get("title")
            if isinstance(title, str) and title.startswith(title_prefix):
                return pr.get("number")
        next_url = parse_link_header(link_header)
    return None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_migration(due, forced_migration=None, all_migrations=None, unconfigured=None, issue_migrations=None):
    """Pick the migration to run.

    Returns ``(selected, selected_file, selected_issue, selected_target_metric,
    selected_metric_direction, selected_strategy, deferred, error)``.
    """
    all_migrations = all_migrations or {}
    unconfigured = unconfigured or []
    issue_migrations = issue_migrations or {}
    if forced_migration:
        if forced_migration not in all_migrations:
            return (
                None, None, None, None, "higher", "auto", [],
                "requested migration '{}' not found. Available migrations: {}".format(
                    forced_migration, list(all_migrations.keys())
                ),
            )
        if forced_migration in unconfigured:
            return (
                None, None, None, None, "higher", "auto", [],
                "requested migration '{}' is unconfigured (has placeholders).".format(
                    forced_migration
                ),
            )
        selected = forced_migration
        selected_file = all_migrations[forced_migration]
        deferred = [p["name"] for p in due if p["name"] != forced_migration]
        selected_issue = (
            issue_migrations[selected]["issue_number"] if selected in issue_migrations else None
        )
        selected_target_metric = None
        selected_metric_direction = None
        selected_strategy = None
        for p in due:
            if p["name"] == forced_migration:
                selected_target_metric = p.get("target_metric")
                selected_metric_direction = p.get("metric_direction")
                selected_strategy = p.get("strategy")
                break
        if selected_target_metric is None:
            selected_target_metric = _parse_target_metric_from_file(selected_file)
        if selected_metric_direction is None:
            selected_metric_direction = _parse_metric_direction_from_file(selected_file)
        if selected_strategy is None:
            selected_strategy = _parse_strategy_from_file(selected_file)
        return (
            selected,
            selected_file,
            selected_issue,
            selected_target_metric,
            selected_metric_direction,
            selected_strategy,
            deferred,
            None,
        )

    if due:
        # Normal scheduling: pick the single most-overdue migration.
        # ``last_run`` of None/empty sorts first (never run).
        due_sorted = sorted(due, key=lambda p: p["last_run"] or "")
        selected = due_sorted[0]["name"]
        selected_file = due_sorted[0]["file"]
        selected_target_metric = due_sorted[0].get("target_metric")
        selected_metric_direction = due_sorted[0].get("metric_direction") or "higher"
        selected_strategy = due_sorted[0].get("strategy") or "auto"
        deferred = [p["name"] for p in due_sorted[1:]]
        selected_issue = (
            issue_migrations[selected]["issue_number"] if selected in issue_migrations else None
        )
        return (
            selected,
            selected_file,
            selected_issue,
            selected_target_metric,
            selected_metric_direction,
            selected_strategy,
            deferred,
            None,
        )

    return None, None, None, None, "higher", "auto", [], None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    forced_migration = os.environ.get("CRANE_MIGRATION", "").strip()

    _bootstrap_template_if_missing()

    # Find all migration files from all locations:
    # 1. Directory-based: .crane/migrations/<name>/migration.md (preferred)
    # 2. Bare markdown:   .crane/migrations/<name>.md (simple)
    # 3. Issue-based:     GitHub issues with the 'crane-migration' label
    migration_files = []
    migration_files.extend(_scan_directory_migrations())
    migration_files.extend(_scan_bare_migrations())
    issue_files, issue_migrations = _fetch_issue_migrations(repo, github_token)
    migration_files.extend(issue_files)

    if not migration_files:
        # Fallback to single-file locations
        for path in [".crane/migration.md", "migration.md"]:
            if os.path.isfile(path):
                migration_files = [path]
                break

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not migration_files:
        print("NO_MIGRATIONS_FOUND")
        with open(OUTPUT_FILE, "w") as f:
            json.dump(
                {
                    "due": [],
                    "skipped": [],
                    "unconfigured": [],
                    "no_migrations": True,
                    "head_branch": None,
                    "existing_pr": None,
                },
                f,
            )
        sys.exit(0)

    now = datetime.now(timezone.utc)
    due = []
    skipped = []
    unconfigured = []
    all_migrations = {}  # name -> file path

    for pf in migration_files:
        name = get_migration_name(pf)
        all_migrations[name] = pf
        with open(pf) as f:
            content = f.read()

        if is_unconfigured(content):
            unconfigured.append(name)
            continue

        fm = parse_migration_frontmatter(content)
        schedule_delta = fm["schedule_delta"]
        target_metric = fm["target_metric"]
        metric_direction = fm["metric_direction"]
        strategy = fm["strategy"]
        if fm["target_metric_invalid"] is not None:
            print("  Warning: {} has invalid target-metric value: {}".format(name, fm["target_metric_invalid"]))
        if fm["metric_direction_invalid"] is not None:
            print(
                "  Warning: {} has invalid metric_direction value: {!r} (must be 'higher' or 'lower'); defaulting to 'higher'".format(
                    name, fm["metric_direction_invalid"]
                )
            )
        if fm["strategy_invalid"] is not None:
            print(
                "  Warning: {} has invalid strategy value: {!r} (must be 'in-place', 'greenfield', or 'auto'); defaulting to 'auto'".format(
                    name, fm["strategy_invalid"]
                )
            )

        # Read state from repo-memory
        state = read_migration_state(name)
        if state:
            print(
                "  {}: last_run={}, iteration_count={}".format(
                    name, state.get("last_run"), state.get("iteration_count")
                )
            )
        else:
            print("  {}: no state found (first run)".format(name))

        last_run = None
        lr = state.get("last_run")
        if lr:
            try:
                last_run = datetime.fromisoformat(lr.replace("Z", "+00:00"))
            except ValueError:
                pass

        should_skip, reason = check_skip_conditions(state)
        if should_skip:
            skipped.append({"name": name, "reason": reason})
            continue

        # Check if due based on per-migration schedule
        if schedule_delta and last_run and now - last_run < schedule_delta:
            skipped.append(
                {
                    "name": name,
                    "reason": "not due yet",
                    "next_due": (last_run + schedule_delta).isoformat(),
                }
            )
            continue

        due.append({
            "name": name,
            "last_run": lr,
            "file": pf,
            "target_metric": target_metric,
            "metric_direction": metric_direction,
            "strategy": strategy,
        })

    selected, selected_file, selected_issue, selected_target_metric, selected_metric_direction, selected_strategy, deferred, error = (
        select_migration(due, forced_migration, all_migrations, unconfigured, issue_migrations)
    )

    if error:
        print("ERROR: {}".format(error))
        sys.exit(1)

    if forced_migration and selected:
        print("FORCED: running migration '{}' (manual dispatch)".format(forced_migration))

    # Look up the existing draft PR (if any) for the selected migration.
    head_branch = None
    existing_pr = None
    if selected:
        head_branch = "crane/{}".format(selected)
        try:
            existing_pr = find_existing_pr_for_branch(repo, selected, github_token)
        except Exception as e:  # noqa: BLE001 -- best-effort lookup
            print("  Warning: existing PR lookup failed for {}: {}".format(selected, e))
            existing_pr = None

    result = {
        "selected": selected,
        "selected_file": selected_file,
        "selected_issue": selected_issue,
        "selected_target_metric": selected_target_metric,
        "selected_metric_direction": selected_metric_direction,
        "selected_strategy": selected_strategy,
        "state_file_size_bytes": get_state_file_size(selected) if selected else 0,
        "state_file_max_bytes": STATE_FILE_MAX_BYTES,
        "issue_migrations": {
            name: info["issue_number"] for name, info in issue_migrations.items()
        },
        "deferred": deferred,
        "skipped": skipped,
        "unconfigured": unconfigured,
        "no_migrations": False,
        "head_branch": head_branch,
        "existing_pr": existing_pr,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print("=== Crane Migration Check ===")
    print("Selected migration:      {} ({})".format(selected or "(none)", selected_file or "n/a"))
    print("Deferred (next run):     {}".format(deferred or "(none)"))
    print("Migrations skipped:      {}".format([s["name"] for s in skipped] or "(none)"))
    print("Migrations unconfigured: {}".format(unconfigured or "(none)"))

    if not selected and not unconfigured:
        print("\nNo migrations due this run. Exiting early.")
        sys.exit(1)  # Non-zero exit skips the agent step


if __name__ == "__main__":
    main()
