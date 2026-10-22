/** Server stream payloads (snake_case wire) to the conversation's own types.
 *  Unknown steps and proposals without candidates are dropped. */

import type { CoachProposal, ThinkingStep } from "./coachConversation.ts";

export function toThinkingStep(raw: Record<string, unknown>): ThinkingStep | null {
  switch (raw.step) {
    case "READ_TRAINING_LOAD":
      return {
        kind: "READ_TRAINING_LOAD",
        observationDays: Number(raw.observation_days ?? 0),
        loadRatio: typeof raw.load_ratio === "number" ? raw.load_ratio : null,
        activityCount: Number(raw.activity_count ?? 0),
        recentActivityCount: Number(raw.recent_activity_count ?? 0),
        totalDistanceKm: Number(raw.total_distance_km ?? 0),
      };
    case "REVIEWED_GUIDANCE":
      return {
        kind: "REVIEWED_GUIDANCE",
        count: Number(raw.count ?? 0),
        citations: (Array.isArray(raw.citations) ? raw.citations : []).map((entry) => {
          const citation = entry as Record<string, unknown>;
          return {
            evidenceId: String(citation.evidence_id ?? ""),
            title: String(citation.title ?? ""),
            publisher: String(citation.publisher ?? ""),
            sourceUrl: String(citation.source_url ?? ""),
            bodyParts: Array.isArray(citation.body_parts)
              ? citation.body_parts.map(String)
              : [],
            phase: typeof citation.phase === "string" ? citation.phase : null,
          };
        }),
      };
    case "CONSIDERED_OPTIONS":
      return {
        kind: "CONSIDERED_OPTIONS",
        count: Number(raw.count ?? 0),
        personalised: Boolean(raw.personalised),
      };
    default:
      return null;
  }
}

export function toProposal(raw: Record<string, unknown>): CoachProposal | null {
  const facts = (raw.facts ?? {}) as Record<string, unknown>;
  const candidates = Array.isArray(raw.candidates) ? raw.candidates : [];
  if (candidates.length === 0) return null;

  return {
    id: typeof raw.id === "string" ? raw.id : null,
    label: String(raw.label ?? ""),
    changedFacts: Array.isArray(raw.changed_facts) ? raw.changed_facts.map(String) : [],
    accepted: Boolean(raw.accepted),
    abstained: Boolean(raw.abstained),
    confidence: typeof raw.confidence === "number" ? raw.confidence : null,
    speedLossPct: typeof raw.speed_loss_pct === "number" ? raw.speed_loss_pct : null,
    pacingIsExtrapolated: Boolean(raw.pacing_is_extrapolated),
    coachAssigned: Array.isArray(raw.coach_assigned) ? raw.coach_assigned.map(String) : [],
    // absent (an older backend): applying is what it always allowed
    selfApplyAllowed: raw.self_apply_allowed !== false,
    canSendToCoach: raw.can_send_to_coach !== false,
    easyPace: toEasyPace(raw.easy_pace),
    facts: {
      localDate: String(facts.local_date ?? ""),
      temperatureC: typeof facts.temperature_c === "number" ? facts.temperature_c : null,
      humidityPct: typeof facts.humidity_pct === "number" ? facts.humidity_pct : null,
      availableMinutes:
        typeof facts.available_minutes === "number" ? facts.available_minutes : null,
      reportedBodyPart:
        typeof facts.reported_body_part === "string" ? facts.reported_body_part : null,
      reportedSeverityBand:
        typeof facts.reported_severity_band === "string" ? facts.reported_severity_band : null,
    },
    candidates: candidates.map((entry) => {
      const candidate = entry as Record<string, unknown>;
      return {
        candidateId: String(candidate.candidate_id ?? ""),
        workoutType: String(candidate.workout_type ?? ""),
        durationMinutes: Number(candidate.duration_minutes ?? 0),
        distanceKm: Number(candidate.distance_km ?? 0),
        runningAllowed: Boolean(candidate.running_allowed),
        paceRangeSPerKm: toPaceRange(candidate.pace_range_s_per_km),
      };
    }),
  };
}

function toEasyPace(raw: unknown): CoachProposal["easyPace"] {
  const pace = raw as Record<string, unknown> | null;
  if (!pace || typeof pace.s_per_km !== "number") return null;
  return { sPerKm: pace.s_per_km, runs: Number(pace.runs ?? 0), days: Number(pace.days ?? 0) };
}

function toPaceRange(raw: unknown): [number, number] | null {
  return Array.isArray(raw) && raw.length === 2 && raw.every((n) => typeof n === "number")
    ? [raw[0], raw[1]]
    : null;
}
