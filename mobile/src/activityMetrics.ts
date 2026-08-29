export interface ActivityDeviceMetrics {
  avgHeartRate?: number;
  maxHeartRate?: number;
  avgCadenceStepsPerMin?: number;
  maxCadenceStepsPerMin?: number;
  avgStrideLengthM?: number;
  elevationGainM?: number;
  elevationLossM?: number;
  calories?: number;
  aerobicTrainingEffect?: number;
  anaerobicTrainingEffect?: number;
  trainingEffectLabel?: string;
}

export function buildActivityMetricRows(
  m: ActivityDeviceMetrics,
  locale: 'zh-TW' | 'en' = 'zh-TW',
): Array<{ label: string; value: string }> {
  const en = locale === 'en';
  const rows: Array<{ label: string; value: string }> = [];
  if (m.avgHeartRate !== undefined || m.maxHeartRate !== undefined) rows.push({
    label: en ? 'Avg / max heart rate' : '平均／最高心率',
    value: `${m.avgHeartRate ?? '—'} / ${m.maxHeartRate ?? '—'} bpm`,
  });
  if (m.avgCadenceStepsPerMin !== undefined || m.maxCadenceStepsPerMin !== undefined) rows.push({
    label: en ? 'Avg / max cadence' : '平均／最高步頻',
    value: `${m.avgCadenceStepsPerMin ?? '—'} / ${m.maxCadenceStepsPerMin ?? '—'} spm`,
  });
  if (m.avgStrideLengthM !== undefined) rows.push({ label: en ? 'Stride length' : '平均步幅', value: `${m.avgStrideLengthM} m` });
  if (m.elevationGainM !== undefined || m.elevationLossM !== undefined) rows.push({ label: en ? 'Elevation gain / loss' : '爬升／下降', value: `↑${m.elevationGainM ?? 0} / ↓${m.elevationLossM ?? 0} m` });
  if (m.calories !== undefined) rows.push({ label: en ? 'Calories' : '熱量', value: `${m.calories} kcal` });
  if (m.aerobicTrainingEffect !== undefined || m.anaerobicTrainingEffect !== undefined) rows.push({
    label: en ? 'Training effect' : '訓練效果',
    value: `${m.aerobicTrainingEffect ?? '—'} / ${m.anaerobicTrainingEffect ?? '—'}${m.trainingEffectLabel ? ` · ${m.trainingEffectLabel}` : ''}`,
  });
  return rows;
}
