from __future__ import annotations

import os
from pathlib import Path

from app.runtime_env import load_runtime_environment


def test_demo_mode_does_not_prevent_provider_settings_from_loading(monkeypatch):
    env_file = Path(__file__).parent / "fixtures" / "runtime-provider.env"
    monkeypatch.setenv("COMPETITION_DEMO_ONLY", "true")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    load_runtime_environment(env_file)

    assert os.environ["GROQ_API_KEY"] == "gsk_test-provider-key"
    assert os.environ["COMPETITION_DEMO_ONLY"] == "true"


def test_a_process_value_still_wins_so_deployments_can_override_the_file(monkeypatch):
    env_file = Path(__file__).parent / "fixtures" / "runtime-provider.env"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_set-by-the-deployment")

    load_runtime_environment(env_file)

    assert os.environ["GROQ_API_KEY"] == "gsk_set-by-the-deployment"


def test_a_shadowed_provider_key_is_reported_rather_than_silently_honoured(monkeypatch, caplog):
    """The failure this warning exists for.

    A stale key exported in the shell that started the server silently beat
    the .env file, and the only symptom was a coach that timed out. Nothing
    said the file had been ignored.
    """
    env_file = Path(__file__).parent / "fixtures" / "runtime-provider.env"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_stale-key-from-the-shell")

    with caplog.at_level("WARNING"):
        load_runtime_environment(env_file)

    warnings = " ".join(record.message for record in caplog.records)
    assert "GROQ_API_KEY" in warnings
    assert "gsk_stale-key-from-the-shell" not in warnings


def test_a_matching_value_is_not_reported_as_shadowing(monkeypatch, caplog):
    env_file = Path(__file__).parent / "fixtures" / "runtime-provider.env"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test-provider-key")

    with caplog.at_level("WARNING"):
        load_runtime_environment(env_file)

    assert "GROQ_API_KEY" not in " ".join(r.message for r in caplog.records)


def test_settings_absent_from_the_process_are_not_reported(monkeypatch, caplog):
    env_file = Path(__file__).parent / "fixtures" / "runtime-provider.env"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with caplog.at_level("WARNING"):
        load_runtime_environment(env_file)

    assert caplog.records == []
