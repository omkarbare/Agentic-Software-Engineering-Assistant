from coding_agent.utils.redaction import redact


def test_sensitive_values_are_redacted() -> None:
    assert "not-a-real-value" not in redact("api_key=not-a-real-value")
