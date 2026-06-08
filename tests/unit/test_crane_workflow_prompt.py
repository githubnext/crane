from pathlib import Path


WORKFLOW_PROMPT = Path(__file__).parents[2] / "workflows" / "crane.md"


def test_accepted_iteration_summary_contract_is_documented():
    prompt = WORKFLOW_PROMPT.read_text()

    assert "Accepted Iteration Summary" in prompt
    assert "single shared source summary" in prompt

    for surface in [
        "PR body",
        "PR comment",
        "migration issue comment",
        "repo-memory iteration history",
    ]:
        assert surface in prompt

    assert "add-comment" in prompt
    assert "push-to-pull-request-branch" in prompt
