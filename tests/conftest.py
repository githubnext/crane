"""Test fixtures for the standalone Crane scheduler.

The scheduler logic lives in ``workflows/scripts/crane_scheduler.py`` and is
also distributed at ``.github/workflows/scripts/crane_scheduler.py`` (the
dogfooded deploy copy). Tests import the source module directly via importlib.
"""

import importlib.util
import os
import sys

# Path to the standalone scheduler script (source-of-truth lives in workflows/).
SCHEDULER_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "workflows",
        "scripts",
        "crane_scheduler.py",
    )
)

_spec = importlib.util.spec_from_file_location("crane_scheduler", SCHEDULER_PATH)
crane_scheduler = importlib.util.module_from_spec(_spec)
sys.modules["crane_scheduler"] = crane_scheduler
_spec.loader.exec_module(crane_scheduler)


# Function map for direct access in tests.
_funcs = {
    "parse_schedule": crane_scheduler.parse_schedule,
    "parse_machine_state": crane_scheduler.parse_machine_state,
    "parse_migration_frontmatter": crane_scheduler.parse_migration_frontmatter,
    "get_migration_name": crane_scheduler.get_migration_name,
    "slugify_issue_title": crane_scheduler.slugify_issue_title,
    "parse_link_header": crane_scheduler.parse_link_header,
    "is_unconfigured": crane_scheduler.is_unconfigured,
    "is_completed_state": crane_scheduler.is_completed_state,
    "check_skip_conditions": crane_scheduler.check_skip_conditions,
    "evaluate_completed_label_recovery": crane_scheduler.evaluate_completed_label_recovery,
    "get_pr_head_check_gate": crane_scheduler.get_pr_head_check_gate,
    "select_migration": crane_scheduler.select_migration,
}
