/** The Coach Conversation's phases.
 *
 *  One value, not a handful of booleans: the coach cannot be thinking and
 *  streaming at once, and a proposal cannot be awaiting acceptance while the
 *  answer is still arriving. Making those states unrepresentable is cheaper
 *  than remembering to keep three flags consistent.
 */

/** One piece of reviewed guidance the coach actually consulted. */
export interface Citation {
  evidenceId: string;
  title: string;
  publisher: string;
  sourceUrl: string;
  bodyParts: string[];
  phase: string | null;
}

export type ThinkingStep =
  | { kind: "READ_TRAINING_LOAD"; observationDays: number; loadRatio: number | null }
  | { kind: "REVIEWED_GUIDANCE"; count: number; citations: Citation[] }
  | { kind: "CONSIDERED_OPTIONS"; count: number; personalised: boolean };

export interface CoachProposal {
  /** Null only when the record could not be written; the card then has
   *  nothing to accept, so acceptance is not offered. */
  id: string | null;
  label: string;
  changedFacts: string[];
  accepted: boolean;
  abstained: boolean;
  confidence: number | null;
  speedLossPct: number | null;
  pacingIsExtrapolated: boolean;
  facts: {
    localDate: string;
    temperatureC: number | null;
    humidityPct: number | null;
    availableMinutes: number | null;
    reportedBodyPart: string | null;
    reportedSeverityBand: string | null;
  };
  candidates: Array<{
    candidateId: string;
    workoutType: string;
    durationMinutes: number;
    distanceKm: number;
    runningAllowed: boolean;
  }>;
}

export type CoachPhase =
  | { kind: "idle" }
  | { kind: "thinking"; steps: ThinkingStep[] }
  | { kind: "streaming"; steps: ThinkingStep[]; text: string }
  | { kind: "proposal"; steps: ThinkingStep[]; text: string; proposal: CoachProposal }
  | { kind: "failed"; text: string };

export type CoachEvent =
  | { type: "ASKED" }
  | { type: "STEP"; step: ThinkingStep }
  | { type: "DELTA"; delta: string }
  | { type: "PROPOSED"; proposal: CoachProposal }
  | { type: "SETTLED" }
  | { type: "FAILED"; text: string }
  | { type: "PROPOSAL_DISMISSED" }
  | { type: "PROPOSAL_ACCEPTED" };

export const IDLE: CoachPhase = { kind: "idle" };

function stepsOf(phase: CoachPhase): ThinkingStep[] {
  return phase.kind === "thinking" ||
    phase.kind === "streaming" ||
    phase.kind === "proposal"
    ? phase.steps
    : [];
}

function textOf(phase: CoachPhase): string {
  return phase.kind === "streaming" || phase.kind === "proposal" ? phase.text : "";
}

export function coachPhaseReducer(phase: CoachPhase, event: CoachEvent): CoachPhase {
  switch (event.type) {
    case "ASKED":
      return { kind: "thinking", steps: [] };

    case "STEP":
      // A step that arrives once the answer has started is still worth
      // recording, but it must not throw the conversation back to thinking.
      if (phase.kind === "thinking") {
        return { kind: "thinking", steps: [...phase.steps, event.step] };
      }
      if (phase.kind === "streaming" || phase.kind === "proposal") {
        return { ...phase, steps: [...phase.steps, event.step] };
      }
      return phase;

    case "DELTA":
      if (phase.kind === "failed" || phase.kind === "idle") return phase;
      return {
        kind: "streaming",
        steps: stepsOf(phase),
        text: textOf(phase) + event.delta,
      };

    case "PROPOSED":
      if (phase.kind === "idle" || phase.kind === "failed") return phase;
      return {
        kind: "proposal",
        steps: stepsOf(phase),
        text: textOf(phase),
        proposal: event.proposal,
      };

    case "SETTLED":
      // An answer that never produced any text is an outage, not an answer.
      if (phase.kind === "thinking") {
        return phase.steps.length === 0 ? IDLE : { kind: "streaming", steps: phase.steps, text: "" };
      }
      return phase;

    case "FAILED":
      return { kind: "failed", text: event.text };

    case "PROPOSAL_DISMISSED":
    case "PROPOSAL_ACCEPTED":
      // Either way the proposal leaves the conversation; only acceptance
      // changes anything, and that happens outside this reducer.
      return phase.kind === "proposal"
        ? { kind: "streaming", steps: phase.steps, text: phase.text }
        : phase;

    default:
      return phase;
  }
}

/** True while the Athlete should not be able to send another question. */
export function isBusy(phase: CoachPhase): boolean {
  return phase.kind === "thinking" || phase.kind === "streaming";
}

/** What the coach consulted for this answer, if anything. */
export function citationsOf(phase: CoachPhase): Citation[] {
  for (const step of stepsOf(phase)) {
    if (step.kind === "REVIEWED_GUIDANCE") return step.citations;
  }
  return [];
}

/** The text to render for this phase, if any. */
export function visibleText(phase: CoachPhase): string {
  return phase.kind === "failed" ? phase.text : textOf(phase);
}
