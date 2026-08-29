import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRecommendationView, RECOMMENDATION_DISCLAIMER } from './recommendation.ts';
import type { GuidanceInput, WeatherInput } from './recommendation.ts';

const guidance: GuidanceInput = {
  local_date: '2026-08-29',
  recommendation: {
    workout_type: 'Easy aerobic run',
    duration_minutes: 45,
    distance_km: 7,
    target_pace_sec_per_km: 330,
    intensity_label: 'EASY',
    algorithm_version: 'rec-2026-03',
  },
  tone_text: 'Keep it relaxed and enjoy the run.',
  tone_reviewed_by: 'coach-education-team',
};

const weather: WeatherInput = {
  state: 'LIVE',
  temperature_c: 29.4,
  humidity_pct: 70,
  pace_adjustment_sec_per_km: 12,
};

test('formats duration, distance and target pace from the server fields', () => {
  const v = buildRecommendationView(guidance, weather);
  assert.equal(v.durationLabel, '45 min');
  assert.equal(v.distanceLabel, '7.0 km');
  assert.equal(v.targetPaceLabel, "5'30\"");
  assert.equal(v.workoutType, 'Easy aerobic run');
});

test('weather-adjusted pace = target pace + server adjustment, formatted', () => {
  const v = buildRecommendationView(guidance, weather);
  assert.equal(v.weatherAdjustedPaceLabel, "5'42\"");
  assert.equal(v.weatherAdjustmentSeconds, 12);
});

test('adjusted pace is null (not the raw pace) when weather is UNAVAILABLE', () => {
  const v = buildRecommendationView(guidance, { ...weather, state: 'UNAVAILABLE' });
  assert.equal(v.weatherAdjustedPaceLabel, null);
  assert.equal(v.weatherAdjustmentSeconds, null);
});

test('adjusted pace is null when the adjustment field is null', () => {
  const v = buildRecommendationView(guidance, { ...weather, pace_adjustment_sec_per_km: null });
  assert.equal(v.weatherAdjustedPaceLabel, null);
});

test('adjusted pace is null when there is no weather response at all', () => {
  const v = buildRecommendationView(guidance, null);
  assert.equal(v.weatherAdjustedPaceLabel, null);
});

test('adjusted pace is null when target pace is null', () => {
  const g = { ...guidance, recommendation: { ...guidance.recommendation, target_pace_sec_per_km: null } };
  const v = buildRecommendationView(g, weather);
  assert.equal(v.targetPaceLabel, '--');
  assert.equal(v.weatherAdjustedPaceLabel, null);
});

test('carries the deterministic-engine and human-reviewed-tone disclaimer facts', () => {
  const v = buildRecommendationView(guidance, weather);
  assert.equal(v.deterministicEngine, true);
  assert.equal(v.algorithmVersion, 'rec-2026-03');
  assert.equal(v.toneReviewedBy, 'coach-education-team');
  assert.equal(v.toneIsHumanReviewed, true);
});

test('distance label is a dash when the server distance is null', () => {
  const g = { ...guidance, recommendation: { ...guidance.recommendation, distance_km: null } };
  assert.equal(buildRecommendationView(g, weather).distanceLabel, '--');
});

test('disclaimer strings exist for both locales and name the rule engine', () => {
  assert.match(RECOMMENDATION_DISCLAIMER.en.toLowerCase(), /rule engine/);
  assert.ok(RECOMMENDATION_DISCLAIMER['zh-TW'].length > 0);
});
