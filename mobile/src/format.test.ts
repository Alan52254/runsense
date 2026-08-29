import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatPace,
  formatLoad,
  formatRatio,
  formatLocalDate,
  formatTemperature,
  formatElapsed,
} from './format.ts';

test('formatPace: seconds per km to m\'ss"', () => {
  assert.equal(formatPace(330), "5'30\"");
  assert.equal(formatPace(300), "5'00\"");
  assert.equal(formatPace(365), "6'05\"");
});

test('formatPace: unknown / invalid input renders a dash', () => {
  assert.equal(formatPace(null), '--');
  assert.equal(formatPace(undefined), '--');
  assert.equal(formatPace(0), '--');
  assert.equal(formatPace(-10), '--');
  assert.equal(formatPace(Number.NaN), '--');
});

test('formatLoad: one decimal or dash', () => {
  assert.equal(formatLoad(42), '42.0');
  assert.equal(formatLoad(12.34), '12.3');
  assert.equal(formatLoad(null), '--');
});

test('formatRatio: two decimals, neutral label when absent, never a band word', () => {
  assert.equal(formatRatio(1.234), '1.23');
  assert.equal(formatRatio(null), 'not enough data yet');
  const label = formatRatio(null).toLowerCase();
  for (const banned of ['safe', 'danger', 'warning', 'high', 'low', 'risk']) {
    assert.ok(!label.includes(banned), `ratio label must not contain "${banned}"`);
  }
});

test('formatLocalDate: parses a calendar date without timezone drift', () => {
  assert.equal(formatLocalDate('2026-08-29', 'en'), 'Sat, Aug 29');
  assert.equal(formatLocalDate('2026-08-29T15:00:00Z', 'en'), 'Sat, Aug 29');
  assert.equal(formatLocalDate('not-a-date', 'en'), 'not-a-date');
});

test('formatTemperature: rounded celsius or dash', () => {
  assert.equal(formatTemperature(21.6), '22°C');
  assert.equal(formatTemperature(null), '--');
});

test('formatElapsed: zero-padded mm:ss, clamps negatives', () => {
  assert.equal(formatElapsed(0), '00:00');
  assert.equal(formatElapsed(65), '01:05');
  assert.equal(formatElapsed(3599), '59:59');
  assert.equal(formatElapsed(-5), '00:00');
});
