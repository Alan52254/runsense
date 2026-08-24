"""Application-level errors that must not leak implementation detail.

See design.md Decision 9: a malformed actor identifier must fail closed
with a generic authorization error, not a raw database/cast error.
"""

from __future__ import annotations


class AuthorizationError(Exception):
    """Raised when the request cannot be authorized. Maps to a generic 403."""


class ProfileTimezoneNotSetError(Exception):
    """Raised when the actor has no profile timezone set. Maps to a 422."""


class DemoCredentialsRejectedError(Exception):
    """Raised for every invalid demo-login credential pair. Maps to a generic 401."""


class IdempotencyKeyReusedWithDifferentPayloadError(Exception):
    """Raised when (athlete_id, client_mutation_id) already exists with a
    different semantic payload. Maps to a 409."""

    def __init__(self, existing_id: str, client_mutation_id: str) -> None:
        self.existing_id = existing_id
        self.client_mutation_id = client_mutation_id
        super().__init__(
            f"client_mutation_id {client_mutation_id} already used with a different payload"
        )


class RestDayConflictsWithActivityError(Exception):
    """Raised when an Athlete tries to confirm rest on an activity date."""


class EmptyProfileUpdateError(Exception):
    """Raised when PATCH /profile is called with neither field set. Maps to a 422."""


class TeamAthleteNotFoundError(Exception):
    """Raised when a Coach Roster Row cannot be found for the requested athlete.

    Covers "athlete_id has no ACTIVE athlete Team Membership in this team" and
    "athlete_id's Team Membership is LEFT" identically (design.md-style
    non-leak posture, matching AuthorizationError's generic-403 precedent):
    a departed athlete's row must be genuinely absent, not distinguishable
    from "never existed". Maps to a 404.
    """


class SessionNotFoundError(Exception):
    """Raised by DELETE /me/settings/sessions/{id} when the session id does
    not belong to the actor (or doesn't exist). Maps to a 404."""


class InvalidMfaCodeError(Exception):
    """Raised by POST /me/settings/mfa/verify for any code other than the
    fixed demo code. Maps to a 422 -- this is a demo-only MFA-satisfied
    toggle, not a real TOTP/SMS verification (see backend/README.md)."""


class AssignmentAthleteNotEligibleError(Exception):
    """Raised by POST /teams/{team_id}/assignments when the target athlete
    is not an ACTIVE athlete Team Membership of that team. Same non-leak
    posture as TeamAthleteNotFoundError. Maps to a 404."""
