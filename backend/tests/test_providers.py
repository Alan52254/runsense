import pytest

from app.providers import (
    InMemoryProfileTimezoneProvider,
    NotImplementedCurrentActorProvider,
    NotImplementedProfileTimezoneProvider,
    StaticCurrentActorProvider,
)


def test_production_default_actor_provider_fails_loudly():
    """No silent 'anonymous actor' fallback -- see design.md Decision 10."""
    with pytest.raises(NotImplementedError):
        NotImplementedCurrentActorProvider().get_current_actor_id()


def test_production_default_timezone_provider_fails_loudly():
    with pytest.raises(NotImplementedError):
        NotImplementedProfileTimezoneProvider().get_profile_timezone("some-actor")


def test_static_actor_provider_returns_configured_id():
    provider = StaticCurrentActorProvider("actor-123")
    assert provider.get_current_actor_id() == "actor-123"


def test_static_actor_provider_can_represent_missing_actor():
    provider = StaticCurrentActorProvider(None)
    assert provider.get_current_actor_id() is None


def test_in_memory_timezone_provider_returns_none_when_unset():
    provider = InMemoryProfileTimezoneProvider()
    assert provider.get_profile_timezone("actor-123") is None


def test_in_memory_timezone_provider_returns_configured_timezone():
    provider = InMemoryProfileTimezoneProvider({"actor-123": "Asia/Taipei"})
    assert provider.get_profile_timezone("actor-123") == "Asia/Taipei"
