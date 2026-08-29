import test from 'node:test';
import assert from 'node:assert/strict';
import { buildActivityMetricRows } from './activityMetrics.ts';

test('Garmin history exposes every monitored summary metric', () => {
  const rows = buildActivityMetricRows({
    avgHeartRate: 151,
    maxHeartRate: 188,
    avgCadenceStepsPerMin: 176,
    maxCadenceStepsPerMin: 190,
    avgStrideLengthM: 1.12,
    elevationGainM: 84,
    elevationLossM: 79,
    calories: 622,
    aerobicTrainingEffect: 3.4,
    anaerobicTrainingEffect: 1.2,
    trainingEffectLabel: 'AEROBIC_BASE',
  }, 'zh-TW');

  assert.deepEqual(rows.map((row) => row.label), [
    '平均／最高心率', '平均／最高步頻', '平均步幅', '爬升／下降', '熱量', '訓練效果',
  ]);
  assert.equal(rows[0].value, '151 / 188 bpm');
  assert.equal(rows[1].value, '176 / 190 spm');
});
