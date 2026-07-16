from agent.source_hygiene import is_notice_only_source_title


def test_notice_only_titles_exclude_notices_without_blocking_interventions() -> None:
    assert is_notice_only_source_title("Correction: Trial results")
    assert is_notice_only_source_title("Author Correction: Trial results")
    assert is_notice_only_source_title("Retraction Note: Trial results")
    assert is_notice_only_source_title("Expression of Concern: Trial results")
    assert not is_notice_only_source_title("Correction of vitamin D deficiency in adults")
