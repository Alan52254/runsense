import test from 'node:test';
import assert from 'node:assert/strict';
import {
  HEALTH_COACH_DISCLAIMER,
} from './healthCoach.ts';

test('health guidance disclaimer is explicit in both locales', () => {
  assert.match(HEALTH_COACH_DISCLAIMER['zh-TW'], /不能取代/);
  assert.match(HEALTH_COACH_DISCLAIMER.en.toLowerCase(), /not a substitute/);
  assert.match(HEALTH_COACH_DISCLAIMER.en.toLowerCase(), /diagnosis or treatment/);
});
