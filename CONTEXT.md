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
A Local Training Date that an Athlete has explicitly identified as rest. It is a canonical athlete-owned fact, not an inference from silence.
_Avoid_: Empty day, no-workout day

**Missing Training Data**:
A Local Training Date with neither a Completed Activity nor an explicit Confirmed Rest Day. It conveys no conclusion about whether the Athlete rested.
_Avoid_: Rest day, zero-load day

**Training Load Trend**:
A date-ordered view of Athlete training load whose values remain associated with their source unit.
_Avoid_: Alert, readiness score

**Observation Day**:
A Local Training Date supported by at least one Completed Activity for the relevant unit or by a Confirmed Rest Day. Multiple facts on one date still count as one observation.
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
