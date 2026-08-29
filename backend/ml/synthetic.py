"""Deterministic, de-identified synthetic fixtures for the offline scaffold.

These rows are the *only* data the scaffold ever trains or evaluates on. They
carry no athlete identity, no calendar dates, no free text, and no location --
only opaque integer surrogates and contract features. A latent per-athlete
preference model makes the accepted candidate learnable-but-noisy; a fraction
of athletes get a deliberately short history (cold start) and a fraction of
decisions are triage escalations where the rest option is always accepted.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from ml.feature_contract import (
    FeatureRow,
    derive_interaction_features,
    feature_names,
    validate_row,
)


@dataclass(frozen=True)
class SyntheticConfig:
    n_athletes: int = 8
    days_per_athlete: int = 45
    candidates_per_day: int = 3
    cold_start_athletes: int = 2
    cold_start_days: int = 4
    triage_escalation_rate: float = 0.06
    seed: int = 0


_INTENSITY_PROFILE = {
    0: (0.0, 0),      # rest: 0 km, 0 min
    1: (3.0, 22),     # recovery
    2: (7.0, 40),     # easy
    3: (11.0, 58),    # steady
}


def _candidate_intensities(rng: random.Random, k: int) -> list[int]:
    pool = [0, 1, 2, 3]
    if k >= 4:
        return pool[:k]
    # Always include a rest option and a spread of running options.
    chosen = {0}
    while len(chosen) < k:
        chosen.add(rng.choice([1, 2, 3]))
    return sorted(chosen)


def generate_synthetic_observations(
    config: SyntheticConfig | None = None,
    **overrides: object,
) -> list[FeatureRow]:
    cfg = config or SyntheticConfig()
    if overrides:
        cfg = SyntheticConfig(**{**cfg.__dict__, **overrides})  # type: ignore[arg-type]

    rng = random.Random(cfg.seed)
    rows: list[FeatureRow] = []
    query_id = 0
    names = set(feature_names())

    for athlete in range(cfg.n_athletes):
        is_cold = athlete < cfg.cold_start_athletes
        history = cfg.cold_start_days if is_cold else cfg.days_per_athlete

        # Latent, de-identified per-athlete traits.
        preferred_intensity = rng.choice([1, 2, 2, 3])
        load_sensitivity = rng.uniform(0.8, 1.8)
        heat_sensitivity = rng.uniform(0.3, 1.2)
        base_chronic = rng.uniform(180.0, 420.0)
        usual_temp = rng.uniform(8.0, 26.0)
        noise = rng.uniform(0.4, 1.1)

        chronic = base_chronic
        for day in range(history):
            time_index = day  # all athletes advance on a shared integer clock
            observation_days = day

            acute = max(
                0.0,
                chronic * rng.uniform(0.6, 1.35) + rng.gauss(0.0, 25.0),
            )
            ratio = acute / chronic if chronic > 0 else 1.0
            ramp = (ratio - 1.0) * 100.0 + rng.gauss(0.0, 6.0)
            days_since_last = rng.choice([0, 1, 1, 2, 2, 3, 5])
            session_count_7d = max(0, min(10, int(round(rng.gauss(4.0, 1.4)))))
            temp_c = usual_temp + rng.gauss(0.0, 4.5)
            temp_vs_normal = temp_c - usual_temp
            weather_actionable = 1.0 if rng.random() > 0.12 else 0.0
            soreness = rng.choices([0, 1, 2, 3], weights=[5, 4, 2, 1])[0]
            resting_hr_delta = rng.gauss(soreness * 1.5, 3.0)
            sleep_hours = min(11.0, max(3.5, rng.gauss(7.4, 1.0)))

            escalated = rng.random() < cfg.triage_escalation_rate
            self_care = (not escalated) and soreness >= 2 and rng.random() < 0.4

            # The intensity that best fits *observable* state. This is what a
            # de-identified model can actually learn; the per-athlete latent
            # terms below are deliberately small so they act as realistic noise
            # rather than the dominant signal.
            if ratio < 1.0 and soreness == 0 and temp_vs_normal < 4.0:
                observable_target = 3 if days_since_last >= 3 else 2
            elif ratio < 1.15 and soreness <= 1:
                observable_target = 2
            elif ratio < 1.3 and soreness <= 2:
                observable_target = 1
            else:
                observable_target = 0

            intensities = _candidate_intensities(rng, cfg.candidates_per_day)
            candidate_utils: list[tuple[str, int, float]] = []
            for slot, intensity in enumerate(intensities):
                if escalated:
                    util = 5.0 if intensity == 0 else -5.0 + rng.gauss(0.0, 0.2)
                else:
                    fit_term = -abs(intensity - observable_target) * 1.3
                    load_term = -max(0.0, ratio - 1.05) * intensity * load_sensitivity * 1.1
                    soreness_term = -soreness * intensity * 0.30
                    heat_term = -max(0.0, temp_vs_normal - 2.0) * intensity * heat_sensitivity * 0.10
                    latent_pref = -abs(intensity - preferred_intensity) * 0.20
                    util = (
                        fit_term
                        + load_term
                        + soreness_term
                        + heat_term
                        + latent_pref
                        + rng.gauss(0.0, 0.45 * noise)
                    )
                candidate_utils.append((f"cand-{query_id}-{slot}", intensity, util))

            best_id = max(candidate_utils, key=lambda t: t[2])[0]
            for candidate_id, intensity, _util in candidate_utils:
                dist, dur = _INTENSITY_PROFILE[intensity]
                features = {
                    "acute_load": round(acute, 2),
                    "chronic_load": round(chronic, 2),
                    "acute_chronic_ratio": round(ratio, 4),
                    "load_ramp_pct": round(ramp, 3),
                    "observation_days": float(observation_days),
                    "days_since_last_activity": float(days_since_last),
                    "session_count_7d": float(session_count_7d),
                    "temp_c": round(temp_c, 2),
                    "temp_vs_normal_c": round(temp_vs_normal, 3),
                    "weather_actionable": weather_actionable,
                    "triage_self_care": 1.0 if self_care else 0.0,
                    "triage_escalated": 1.0 if escalated else 0.0,
                    "candidate_distance_km": float(dist),
                    "candidate_duration_min": float(dur),
                    "candidate_intensity_ord": float(intensity),
                    "soreness_ord": float(soreness),
                    "resting_hr_delta": round(resting_hr_delta, 3),
                    "sleep_hours": round(sleep_hours, 3),
                }
                features.update(derive_interaction_features(features))
                assert set(features) == names, "synthetic row must fill exactly the contract"
                row = FeatureRow(
                    group=athlete,
                    time_index=time_index,
                    query_id=query_id,
                    candidate_id=candidate_id,
                    label=1 if candidate_id == best_id else 0,
                    features=features,
                )
                validate_row(row)
                rows.append(row)

            query_id += 1

            # Chronic load drifts slowly with the athlete's realised acute load.
            chronic = chronic * 0.92 + acute * 0.08

    return rows


def rows_to_records(rows: Sequence[FeatureRow]) -> list[dict[str, object]]:
    """Plain-dict form for JSONL serialisation by the offline scripts."""

    return [
        {
            "group": r.group,
            "time_index": r.time_index,
            "query_id": r.query_id,
            "candidate_id": r.candidate_id,
            "label": r.label,
            "features": dict(r.features),
        }
        for r in rows
    ]


def records_to_rows(records: Sequence[dict[str, object]]) -> list[FeatureRow]:
    out: list[FeatureRow] = []
    for rec in records:
        row = FeatureRow(
            group=int(rec["group"]),
            time_index=int(rec["time_index"]),
            query_id=int(rec["query_id"]),
            candidate_id=str(rec["candidate_id"]),
            label=int(rec["label"]),
            features={k: float(v) for k, v in dict(rec["features"]).items()},
        )
        validate_row(row)
        out.append(row)
    return out
