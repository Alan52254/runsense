# RunSence

RunSence is a clinical-safety-gated, telemetry-driven running coaching platform designed for Garmin native watch and wrist-band runners, combining deterministic injury triage, bounded Digital Twin plan ranking, consent-scoped team coaching, and grounded ReAct guidance.

## Language

### People, Teams & Privacy

**Athlete**:
A runner who owns completed activities, training load, injury reports, daily wellness records, and team consent grants.
_Avoid_: user, runner account, customer

**Coach**:
An active team staff member (`coach`, `head_coach`, or `owner`) permitted to inspect consented athlete telemetry and schedule confirmed plan cards.
_Avoid_: trainer, admin, moderator

**Team**:
A shared training organization connecting Athletes and Coaches through explicit membership status (`ACTIVE`, `INVITED`, `LEFT`).
_Avoid_: club, group, workspace

**Room**:
A team chat space that is either a public `team` room (disclosing no individual telemetry) or a per-athlete `direct` room shared with Coaches.
_Avoid_: channel, thread, chat room

**ConsentGrant**:
A revocable, per-team permission granted by an Athlete over explicit scopes (`activity_summary`, `training_load`, `injury_status`, `injury_detail`).
_Avoid_: share toggle, friend request, permission flag

**RLS (`runsense_runtime`)**:
PostgreSQL forced Row-Level Security (`ENABLE` and `FORCE ROW LEVEL SECURITY`) binding every runtime database read and write to the active actor identity and consent scope.
_Avoid_: app-level filter, soft auth check

### Training Load & Telemetry

**ACWR**:
Acute:Chronic Workload Ratio (7-day acute load divided by 28-day/4 chronic load) tracked as a descriptive input rather than a universal prescription rule.
_Avoid_: injury threshold, risk score

**SessionLoad**:
Quantified physiological strain of a single running session measured in Arbitrary Units (`AU`), derived from post-run RPE or a deterministic heart-rate TRIMP fallback (**Target M3** for HR-TRIMP fallback).
_Avoid_: calorie burn, effort points

**TRIMP / rTSS**:
Heart-rate Training Impulse (`TRIMP`) or pace-based running Training Stress Score (`rTSS`) used to derive `SessionLoad` when a wrist-band runner omits post-run RPE (**Target M3**).
_Avoid_: estimated calories, workout score

**RestDay**:
A confirmed or sync-window-inferred non-running day (`intensity = 0`) representing deliberate recovery rather than missing activity data (**Target M2** in historical feature pipeline).
_Avoid_: missing row, zero entry, skipped log

**El Helou Thermal Speed Loss**:
Sex-stratified quadratic speed-loss curve (El Helou et al., 2012) paired with local climatological acclimatization adjustments to express heat strain relative to normal pace.
_Avoid_: generic heat index, feels-like penalty

**FIT Telemetry**:
One-hertz physiological and lap stream parsed from Garmin `.fit` activity files (heart rate, cadence, speed, laps, timer pauses, and cadence-lock-resistant rolling HR), excluding raw GPS from ML and persistent telemetry tables.
_Avoid_: GPS track, route log

**WellnessBaseline**:
Daily Garmin physiological recovery record (resting heart rate delta, HRV, sleep duration/score, Body Battery, stress, VO2max) compared against an athlete's rolling personal baseline (**Target M3**).
_Avoid_: readiness score, health grade

### Safety Triage & Bounded Planning

**SafetyTriage**:
The deterministic pre-ML, pre-LLM rule assessment (`safety-triage-v1`) classifying reported symptoms and severity into clinical urgency without issuing a medical diagnosis.
_Avoid_: AI safety filter, diagnosis engine

**TriageUrgency**:
Ordered three-level clinical urgency (`EMERGENCY` > `PROMPT_CLINICIAN` > `SELF_CARE_NEXT_STEP`) that downstream components may monotonically escalate but never downgrade.
_Avoid_: risk level, severity tag

**SafetyEnvelope** (`AgentSecurityEnvelope`):
Immutable server-side safety lock initialized before a coaching loop from message red flags and recent injury history so tools and language models cannot downgrade `TriageUrgency` or unblock running (**Target M5**).
_Avoid_: prompt guard, regex filter

**CandidateLadder**:
The deterministic bounded set of pre-approved daily workout templates (`REST_AND_SEEK_CARE` through `STEADY_RUN`) filtered by `TriageUrgency` and available time.
_Avoid_: AI workout, generated plan

**BoundedRanker**:
A learned or rule-based ranker that only reorders pre-approved `CandidateLadder` options without inventing or altering distance, duration, or intensity.
_Avoid_: prescription model, workout generator

**Abstention**:
An explicit ranker deferral to the safest deterministic candidate ordering when safety triage escalates, history is insufficient (<7 days or zero chronic load), calibrated confidence is low, or model artifacts are unavailable (**Target M2** full 5-trigger online enforcement; cold-start abstention in current deterministic ranker).
_Avoid_: model error, silent fallback

**ShadowMode**:
A ranking execution mode where deterministic rules remain authoritative while learned candidate scores are recorded solely in shadow audit fields for offline comparison (current default; **Target M2** promotes official inference to calibrated mode after passing evaluation gates).
_Avoid_: A/B test, production ML

**DigitalTwinSnapshot**:
The de-identified 30-feature physiological-environmental state combining training load, El Helou thermal speed loss, sex calibration, easy-pace baseline, heart rate, and RPE.
_Avoid_: user profile, static bio

**ScenarioOverride**:
A sparse delta of athlete situation facts (date, weather, available minutes, or symptom self-report) that never specifies workout targets and serves as the sole structured input a language model may propose into planning.
_Avoid_: workout edit, plan override

### Coaching Agent & Health Education

**ReAct Coach**:
A multi-step Thought-Action-Observation coaching agent calling verified telemetry, wellness, heat-pace, bounded-ranking, Graph RAG, and media tools inside a `SafetyEnvelope` (**Current**: 2-tool `@AI` scaffold; **Target M5**: unified 7-tool engine across private chat, streaming, and `@AI`).
_Avoid_: freeform chatbot, wrapper prompt

**Numeric Grounding**:
Post-generation verification ensuring every numerical claim in a coach response traces directly to logged telemetry, retrieved context, tool observations, or user messages.
_Avoid_: hallucination check, spellcheck

**Graph RAG**:
Facet-narrowed, provenance-tracked retrieval over reviewed sports-medicine evidence passages where red-flag warnings are never filtered out by body part or topic.
_Avoid_: generic vector search, web RAG

**HealthEducationArtifact**:
An on-demand, triage-bannered PNG, MP4, or SVG educational asset carrying Graph RAG citations and a non-diagnostic disclaimer, rendered locally when paid external media APIs are unavailable (**Target M4**).
_Avoid_: AI art, static article
