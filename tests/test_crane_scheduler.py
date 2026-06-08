import crane_scheduler


def test_parse_machine_state_accepts_emoji_and_ascii_headings():
    emoji_state = """
## ⚙️ Machine State

| Field | Value |
|-------|-------|
| Completed | true |
| Completed Reason | — |
| Iteration Count | 3 |
"""
    ascii_state = """
## [*] Machine State

| Field | Value |
|-------|-------|
| Completed | false |
| Completed Reason | -- |
| Iteration Count | 4 |
"""

    assert crane_scheduler.parse_machine_state(emoji_state) == {
        "completed": True,
        "completed_reason": None,
        "iteration_count": 3,
        "recent_statuses": [],
    }
    assert crane_scheduler.parse_machine_state(ascii_state) == {
        "completed": False,
        "completed_reason": None,
        "iteration_count": 4,
        "recent_statuses": [],
    }


def test_active_issue_label_prevents_completed_state_skip():
    state = {"completed": True}

    assert crane_scheduler.check_skip_conditions(state) == (
        True,
        "completed: target metric reached",
    )
    assert crane_scheduler.check_skip_conditions(state, issue_active=True) == (False, None)


def test_completed_label_is_recovered_when_pr_gate_is_not_confirmed():
    def find_pr(repo, name, token):
        assert (repo, name, token) == ("owner/repo", "migration", "token")
        return 123

    def check_gate(repo, pr_number, token):
        assert (repo, pr_number, token) == ("owner/repo", 123, "token")
        return False, "missing-checks:abc123"

    stale, recovered, event = crane_scheduler.evaluate_completed_label_recovery(
        "migration",
        {"completed": True},
        issue_active=False,
        issue_completed_label=True,
        repo="owner/repo",
        github_token="token",
        find_pr=find_pr,
        check_gate=check_gate,
    )

    assert stale is True
    assert recovered is True
    assert event == ("stale_gate", 123, "missing-checks:abc123")


def test_completed_label_stays_complete_when_pr_gate_passes():
    stale, recovered, event = crane_scheduler.evaluate_completed_label_recovery(
        "migration",
        {"completed": True},
        issue_active=False,
        issue_completed_label=True,
        repo="owner/repo",
        github_token="token",
        find_pr=lambda repo, name, token: 123,
        check_gate=lambda repo, pr_number, token: (True, "passed:abc123"),
    )

    assert stale is False
    assert recovered is False
    assert event == ("confirmed", 123, "passed:abc123")


def test_pr_head_check_gate_requires_at_least_one_successful_check():
    calls = []

    def http_get_json(url, headers):
        calls.append(url)
        if url.endswith("/pulls/5"):
            return {"head": {"sha": "abcdef1234567890"}}, None
        if "check-runs" in url:
            return {
                "check_runs": [
                    {"name": "unit", "status": "completed", "conclusion": "success"},
                    {"name": "lint", "status": "completed", "conclusion": "success"},
                ]
            }, None
        raise AssertionError(url)

    assert crane_scheduler.get_pr_head_check_gate(
        "owner/repo",
        5,
        "token",
        http_get_json=http_get_json,
    ) == (True, "passed:abcdef123456")
    assert len(calls) == 2


def test_pr_head_check_gate_rejects_pending_or_failing_checks():
    def http_get_json(url, headers):
        if url.endswith("/pulls/5"):
            return {"head": {"sha": "abcdef1234567890"}}, None
        if "check-runs" in url:
            return {
                "check_runs": [
                    {"name": "unit", "status": "completed", "conclusion": "success"},
                    {"name": "lint", "status": "in_progress", "conclusion": None},
                ]
            }, None
        raise AssertionError(url)

    passed, reason = crane_scheduler.get_pr_head_check_gate(
        "owner/repo",
        5,
        "token",
        http_get_json=http_get_json,
    )

    assert passed is False
    assert reason == "failing:abcdef123456:lint:in_progress:none"
