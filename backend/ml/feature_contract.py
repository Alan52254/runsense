"""De-identified feature contract for offline Plan Ranking experiments.

The contract is the *only* set of signals a learned ranker is allowed to see.
It is deliberately free of anything that identifies a person or a calendar
moment: no athlete id, no user id, no name, no email, no free text, no
location, no wall-clock date. Grouping and ordering are carried by opaque
integer surrogates (``group``, ``time_index``) that are never fed to a model.

Everything here is pure and deterministic. Missing signals fall back to an
explicit per-feature default; out-of-range numeric values are clamped;
non-finite values are treated as missing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class FeatureKind(StrEnum):
    NUMERIC = "NUMERIC"
    BINARY = "BINARY"


@dataclass(frozen=True)
class FeatureSpec:
    """One column of the feature contract."""

    name: str
    kind: FeatureKind
    description: str
    minimum: float
    maximum: float
    default: float

    def clean(self, value: float | None) -> float:
        """Return a finite, in-range float for ``value``.

        ``None`` / NaN / infinity all resolve to :attr:`default`. Binary
        features snap to ``0.0``/``1.0``; numeric features clamp to
        ``[minimum, maximum]``.
        """

        if value is None:
            return float(self.default)
        try:
            v = float(value)
        except (TypeError, ValueError):
            return float(self.default)
        if math.isnan(v) or math.isinf(v):
            return float(self.default)
        if self.kind is FeatureKind.BINARY:
            return 1.0 if v >= 0.5 else 0.0
        return min(self.maximum, max(self.minimum, v))


# Ordered, stable. Index in this tuple == index in the feature vector.
FEATURE_CONTRACT: tuple[FeatureSpec, ...] = (
    FeatureSpec("acute_load", FeatureKind.NUMERIC,
               "7-day rolling session load, source-unit agnostic", 0.0, 4000.0, 0.0),
    FeatureSpec("chronic_load", FeatureKind.NUMERIC,
               "28-day rolling session load, source-unit agnostic", 0.0, 4000.0, 0.0),
    FeatureSpec("acute_chronic_ratio", FeatureKind.NUMERIC,
               "acute_load / chronic_load, one input among several (not a risk score)",
               0.0, 3.0, 1.0),
    FeatureSpec("load_ramp_pct", FeatureKind.NUMERIC,
               "week-over-week load change, percent", -100.0, 300.0, 0.0),
    FeatureSpec("observation_days", FeatureKind.NUMERIC,
               "count of usable observation days available for this athlete so far",
               0.0, 365.0, 0.0),
    FeatureSpec("days_since_last_activity", FeatureKind.NUMERIC,
               "days since the most recent Completed Activity", 0.0, 60.0, 14.0),
    FeatureSpec("session_count_7d", FeatureKind.NUMERIC,
               "number of Completed Activities in the last 7 days", 0.0, 21.0, 0.0),
    FeatureSpec("temp_c", FeatureKind.NUMERIC,
               "current temperature for the athlete's profile city", -30.0, 50.0, 15.0),
    FeatureSpec("temp_vs_normal_c", FeatureKind.NUMERIC,
               "temperature relative to the athlete's usual exposure (physical-"
               "relationship feature, not a raw sensor value)", -25.0, 25.0, 0.0),
    FeatureSpec("weather_actionable", FeatureKind.BINARY,
               "1 when a LIVE/CACHED/STALE Weather Snapshot backs temp features", 0.0, 1.0, 0.0),
    FeatureSpec("triage_self_care", FeatureKind.BINARY,
               "1 when Safety Triage returned self-care-next-step", 0.0, 1.0, 0.0),
    FeatureSpec("triage_escalated", FeatureKind.BINARY,
               "1 when Safety Triage returned emergency or prompt-clinician", 0.0, 1.0, 0.0),
    FeatureSpec("candidate_distance_km", FeatureKind.NUMERIC,
               "distance of the candidate workout being scored", 0.0, 60.0, 0.0),
    FeatureSpec("candidate_duration_min", FeatureKind.NUMERIC,
               "duration of the candidate workout being scored", 0.0, 300.0, 0.0),
    FeatureSpec("candidate_intensity_ord", FeatureKind.NUMERIC,
               "ordinal intensity of the candidate: 0 rest, 1 recovery, 2 easy, 3 steady",
               0.0, 3.0, 1.0),
    FeatureSpec("soreness_ord", FeatureKind.NUMERIC,
               "self-reported soreness band: 0 none .. 3 marked", 0.0, 3.0, 0.0),
    FeatureSpec("resting_hr_delta", FeatureKind.NUMERIC,
               "resting HR minus the athlete's baseline, bpm", -20.0, 30.0, 0.0),
    FeatureSpec("sleep_hours", FeatureKind.NUMERIC,
               "self-reported sleep duration last night, hours", 0.0, 14.0, 7.5),
    # Engineered candidate x state interactions. These encode the physical
    # relationship "harder workout costs more when load / soreness / heat are
    # already high", so a linear baseline can approximate a non-monotonic
    # sweet-spot preference without an explicit tree. (Research note, section 1:
    # prefer features that encode a relationship over raw values.)
    FeatureSpec("candidate_intensity_sq", FeatureKind.NUMERIC,
               "candidate_intensity_ord squared", 0.0, 9.0, 1.0),
    FeatureSpec("load_intensity_pressure", FeatureKind.NUMERIC,
               "max(0, acute_chronic_ratio - 1) * candidate_intensity_ord", 0.0, 9.0, 0.0),
    FeatureSpec("soreness_intensity_pressure", FeatureKind.NUMERIC,
               "soreness_ord * candidate_intensity_ord", 0.0, 9.0, 0.0),
    FeatureSpec("heat_intensity_pressure", FeatureKind.NUMERIC,
               "max(0, temp_vs_normal_c) * candidate_intensity_ord / 10", 0.0, 10.0, 0.0),
    FeatureSpec("freshness_intensity_fit", FeatureKind.NUMERIC,
               "candidate_intensity_ord when rested (>=3 days since last activity), else 0",
               0.0, 3.0, 0.0),
)


def derive_interaction_features(base: Mapping[str, float]) -> dict[str, float]:
    """Compute the engineered interaction columns from base contract signals.

    Pure and deterministic. ``base`` may omit any key (its contract default is
    used). Returned keys are a subset of :data:`FEATURE_CONTRACT` names.
    """

    def g(name: str) -> float:
        spec = FEATURE_CONTRACT[FEATURE_INDEX[name]]
        return spec.clean(base.get(name))

    intensity = g("candidate_intensity_ord")
    ratio = g("acute_chronic_ratio")
    soreness = g("soreness_ord")
    temp_vs_normal = g("temp_vs_normal_c")
    days_since_last = g("days_since_last_activity")
    return {
        "candidate_intensity_sq": intensity * intensity,
        "load_intensity_pressure": max(0.0, ratio - 1.0) * intensity,
        "soreness_intensity_pressure": soreness * intensity,
        "heat_intensity_pressure": max(0.0, temp_vs_normal) * intensity / 10.0,
        "freshness_intensity_fit": intensity if days_since_last >= 3.0 else 0.0,
    }

FEATURE_INDEX: dict[str, int] = {spec.name: i for i, spec in enumerate(FEATURE_CONTRACT)}

# Keys that must never appear in a feature mapping. Presence of any of these is
# treated as a de-identification failure, not a warning.
DISALLOWED_FEATURE_KEYS: frozenset[str] = frozenset({
    "athlete_id", "user_id", "actor_id", "id", "name", "full_name", "email",
    "date", "local_training_date", "created_at", "timestamp", "datetime",
    "latitude", "longitude", "lat", "lon", "city", "location", "geo",
    "notes", "note", "free_text", "comment", "description", "injury_detail",
    "body_part", "raw_payload", "fit_file",
})

# Row-level keys that are structural, not model inputs.
RESERVED_ROW_KEYS: frozenset[str] = frozenset({
    "group", "time_index", "query_id", "candidate_id", "label",
})


@dataclass(frozen=True)
class FeatureRow:
    """One (decision, candidate) pair in a de-identified observation set.

    * ``group`` -- opaque athlete surrogate. Used only to group evaluation
      splits. Never vectorised.
    * ``time_index`` -- monotonic non-negative integer. Used only to order
      observations forward in time. Never vectorised.
    * ``query_id`` -- ties together the candidates shown for one decision.
    * ``label`` -- 1 if this candidate was the one accepted / completed.
    * ``features`` -- mapping restricted to :data:`FEATURE_CONTRACT` names.
    """

    group: int
    time_index: int
    query_id: int
    candidate_id: str
    label: int
    features: Mapping[str, float]


def feature_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in FEATURE_CONTRACT)


class DeidentificationError(ValueError):
    """Raised when a feature mapping carries an identifying or unknown key."""


def validate_features(features: Mapping[str, object]) -> None:
    """Reject identifying keys, unknown keys, and non-numeric values.

    Missing contract keys are allowed -- they resolve to their default in
    :func:`vectorize`.
    """

    known = set(feature_names())
    for key, value in features.items():
        if key in DISALLOWED_FEATURE_KEYS:
            raise DeidentificationError(f"disallowed identifying feature key: {key!r}")
        if key in RESERVED_ROW_KEYS:
            raise DeidentificationError(f"reserved structural key used as feature: {key!r}")
        if key not in known:
            raise DeidentificationError(f"unknown feature key not in contract: {key!r}")
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            continue
        raise DeidentificationError(
            f"feature {key!r} must be numeric, got {type(value).__name__}"
        )


def assert_deidentified(row: FeatureRow) -> None:
    """Structural + content de-identification check for a whole row."""

    if not isinstance(row.group, int) or isinstance(row.group, bool):
        raise DeidentificationError("row.group must be an opaque int surrogate")
    if not isinstance(row.time_index, int) or isinstance(row.time_index, bool):
        raise DeidentificationError("row.time_index must be an int")
    if row.group < 0 or row.time_index < 0 or row.query_id < 0:
        raise DeidentificationError("group/time_index/query_id must be non-negative")
    if not isinstance(row.candidate_id, str) or not row.candidate_id:
        raise DeidentificationError("candidate_id must be a non-empty opaque string")
    validate_features(row.features)


def validate_row(row: FeatureRow) -> None:
    if row.label not in (0, 1):
        raise ValueError(f"label must be 0 or 1, got {row.label!r}")
    assert_deidentified(row)


def vectorize(features: Mapping[str, float] | FeatureRow) -> tuple[float, ...]:
    """Deterministically turn a feature mapping into an ordered vector.

    Accepts a raw mapping or a :class:`FeatureRow`. Unknown / identifying keys
    raise; missing keys use their contract default; values are cleaned.
    """

    mapping: Mapping[str, float]
    mapping = features.features if isinstance(features, FeatureRow) else features
    validate_features(mapping)
    return tuple(spec.clean(mapping.get(spec.name)) for spec in FEATURE_CONTRACT)


def vectorize_rows(rows: list[FeatureRow]) -> tuple[list[tuple[float, ...]], list[int]]:
    """Return ``(X, y)`` for a list of rows, in the given order."""

    X = [vectorize(r) for r in rows]
    y = [int(r.label) for r in rows]
    return X, y
