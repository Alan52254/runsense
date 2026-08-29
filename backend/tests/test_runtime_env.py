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
