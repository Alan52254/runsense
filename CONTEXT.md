# RunSense

RunSense helps runners record completed training and understand training load while keeping athlete-owned data distinct from team access and coaching context.

## Language

**User**:
A person with an identity in RunSense who may act as an athlete or, in later capabilities, a coach.
_Avoid_: Account, login

**Actor**:
The verified User performing the current operation. An Actor is never inferred from a requested target resource.
_Avoid_: Current athlete, target user

**Athlete**:
A User whose completed training and self-reported data are athlete-owned canonical records.
_Avoid_: Runner account, team athlete record

**Completed Activity**:
The canonical record of training an Athlete has already performed, whether entered manually or received from an approved provider.
_Avoid_: Workout plan, team activity

**Manual Workout Entry**:
An Athlete-provided summary used to create a Completed Activity without an external activity provider.
_Avoid_: Manual activity, workout form

**Session Load**:
The workload value associated with one Completed Activity, interpreted together with its unit and source metric.
_Avoid_: Score, effort points

**Local Training Date**:
The Athlete-local calendar date on which a Completed Activity counts for daily training analysis.
_Avoid_: Created date, server date

**Consent Scope**:
A specific category of athlete-owned information that an Athlete currently permits an eligible team role to access.
_Avoid_: Permission flag, team access

**Confirmed Rest Day**:
A Local Training Date that an Athlete has explicitly identified as rest. It is a canonical athlete-owned fact, not an inference from silence. The backend endpoint and schema for this still exist, but the web frontend no longer exposes any way to create one — the product decision is that a day with no record is simply treated as a day with no run.
_Avoid_: Empty day, no-workout day

**Missing Training Data**:
A Local Training Date with no Completed Activity. It conveys no conclusion about whether the Athlete rested, and is never distinguished in the UI from a legacy Confirmed Rest Day.
_Avoid_: Rest day, zero-load day

**Training Load Trend**:
A date-ordered view of Athlete training load whose values remain associated with their source unit.
_Avoid_: Alert, readiness score

**Observation Day**:
A Local Training Date supported by at least one Completed Activity for the relevant unit. Multiple facts on one date still count as one observation. (Legacy Confirmed Rest Day rows created via the backend endpoint directly no longer count here on the frontend's own client-side calculation — see Confirmed Rest Day above.)
_Avoid_: Synced day, calendar day

**Data Quality**:
A neutral description of whether the available observations and units support interpreting a Training Load Trend value. It is not a risk or performance classification.
_Avoid_: Athlete status, warning level

**Demo Persona**:
A seeded competition-only User and Athlete profile used to exercise the demo identity path.
_Avoid_: Test account, production user

## Team & Coaching

**Team**:
A coaching group an Athlete may join, identified by a coach and the athletes who hold membership in it.
_Avoid_: Squad, group, org

**Team Role**:
The level of access a User holds within one Team — `athlete`, `coach`, `head_coach`, or `owner`. A User's Team Role is independent of whether they are an Athlete; the same User could be an Athlete in one Team and a coach in another.
_Avoid_: Permission level, team type

**Team Membership**:
An Athlete's own record of belonging to one Team — its status (`ACTIVE`, `INVITED`, `LEFT`) and when they joined or left. This is the Athlete-side view of the relationship.
_Avoid_: Roster entry, team link

**Coach Roster Row**:
A query-time, per-athlete projection built for a coach from one Athlete's currently granted Consent Scopes. It is never a stored copy of athlete data — revoking a Consent Scope removes the corresponding fields from the next projection, not from a record that has to be deleted.
_Avoid_: Roster copy, athlete record

**Injury Report**:
An Athlete's self-reported summary of a physical issue on a Local Training Date — whether one exists, its severity band, and body part. It never carries free text.
_Avoid_: Injury record, health status

**Injury Report Detail**:
The free-text elaboration of an Injury Report, held separately so its visibility is governed by its own Consent Scope (`injury_detail`) independent of the summary's (`injury_status`).
_Avoid_: Injury note, injury description

**Assigned Workout**:
A workout a coach prescribes to an Athlete for a specific Local Training Date, tracked as `SCHEDULED`, `COMPLETED`, or `MISSED`. Distinct from a Completed Activity, which is what the Athlete actually did.
_Avoid_: Prescription, training plan, workout plan

## Weather & Guidance

**Weather Snapshot**:
The current conditions for the Athlete's profile-selected city, always carrying one of four states (`LIVE`, `CACHED`, `STALE`, `UNAVAILABLE`) so the UI never presents old data as current. Never derived from device location.
_Avoid_: Forecast, current location weather

**Weather Pace Adjustment**:
A transparent estimate of how the Athlete's profile-city conditions may change the pace needed for an equivalent effort. It is contextual guidance, not a prediction of performance or a change to Completed Activity data.
_Avoid_: Weather penalty, guaranteed equivalent pace

**Recommendation Object**:
The deterministic, server-rendered prescription for today (workout type, duration, distance, target pace, intensity) derived from the Athlete's own Training Load Trend. No field on it is ever set by an LLM.
_Avoid_: AI suggestion, generated plan

**Tone Variant**:
One human-pre-reviewed coaching message, selected — never authored — by the LLM from a fixed whitelist to accompany a Recommendation Object. The LLM's only output is which id to pick.
_Avoid_: AI message, generated text

**Safety Triage**:
A deterministic classification of an Athlete's self-reported symptoms into emergency, prompt-clinician, or self-care-next-step handling. It is not a diagnosis and an LLM can never lower its urgency.
_Avoid_: AI diagnosis, injury severity prediction

**Injury Guidance**:
Source-cited educational information and conservative next steps shown after Safety Triage. It never claims a diagnosis, prescribes medication, or replaces a qualified clinician.
_Avoid_: Treatment plan, medical advice, AI doctor

**Coach Conversation**:
An interactive, evidence-assisted explanation of training load, weather, recovery, and self-reported discomfort. It may be generated by an LLM, but it cannot change Safety Triage or directly prescribe a Recommendation Object.
_Avoid_: AI diagnosis, virtual physician, automated prescription

**Evidence Passage**:
A reviewed, source-attributed excerpt available to retrieval for Injury Guidance or a Coach Conversation. Retrieval makes relevant evidence available; it does not prove that generated text is clinically correct.
_Avoid_: AI knowledge, medical truth, model memory

**Training Plan Candidate**:
One bounded workout option generated from reviewed training rules and the Athlete's available observations. It remains a proposal until the Athlete or Coach accepts it.
_Avoid_: Automatic prescription, AI workout

**Plan Ranking**:
An ordering of Training Plan Candidates produced from historical activity, weather, recovery, and self-report features, with confidence and data-coverage metadata. It may abstain and fall back to deterministic ordering.
_Avoid_: Best workout, injury-risk score, readiness score

**Live Run Monitor**:
An Athlete-initiated, single-device timer session (auto-estimated or manually updated distance/pace/heart rate) that produces one Manual Workout Entry when finished. Not GPS tracking — Phase 1 has none (REQ-SCOPE-001) — and not itself an athlete-owned record until saved as a Completed Activity.
_Avoid_: GPS run, live tracking, recording

**Plan Scenario**:
A named set of facts that a Training Plan Candidate set and its Plan Ranking are evaluated against. "Today" is simply the Plan Scenario with nothing overridden. A Plan Scenario carries facts (date, temperature, humidity, available minutes, self-reported discomfort), never prescriptions — it can shift what the Athlete's situation *is*, never what the workout *should be*.
_Avoid_: Simulation, what-if mode, hypothetical plan

**Scenario Override**:
The sparse, serialisable difference between a Plan Scenario and the Athlete's actual facts for that Local Training Date. It is the only artifact an LLM may produce that influences computation, and it has no field for distance, duration, pace, intensity, or workout type — ADR 0002 is enforced by the absence of those fields, not by convention. An invalid Scenario Override is discarded whole; a partially applied one never exists.
_Avoid_: AI plan, prompt parameters, model output

**Resolved Scenario**:
A Scenario Override merged onto the Athlete's actual facts, complete and immutable, and the only input Plan evaluation accepts. It records which facts were overridden so any resulting plan can be explained back to the Athlete.
_Avoid_: Context object, merged input

**Coach Proposal**:
A Ranked Plan produced from an LLM-authored Scenario Override, presented to the Athlete for acceptance. It changes nothing until accepted, and an unaccepted Coach Proposal leaves the Athlete's day untouched. It cannot be accepted for a day that has an Assigned Workout — that day is the coach's (ADR 0003).
_Avoid_: Auto-adjustment, AI-assigned workout

**Coach Suggestion**:
A Coach Proposal the Athlete has sent to their coach, posted in their one-to-one team chat room. Sending it schedules nothing; the coach may turn it into a plan card and, once they confirm it, an Assigned Workout.
_Avoid_: AI schedule, auto-assignment
