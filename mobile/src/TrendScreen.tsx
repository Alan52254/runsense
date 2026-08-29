import { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { ActivityIndicator, Button, ScrollView, StyleSheet, Text, View } from 'react-native';
import { TrainingLoadPoint, TrainingLoadTrendResponse, getTrainingLoadTrend } from './api';
import { useSession } from './SessionContext';
import DateField from './DateField';
import RestDayControl from './RestDayControl';

type LoadState =
  | { kind: 'loading' }
  | { kind: 'loaded'; data: TrainingLoadTrendResponse }
  | { kind: 'error' };

// REQ-METRIC-001 / spec.md "Data Quality Is Shown as Neutral Text, Never
// as an Alert": every point in this screen uses the SAME plain style
// regardless of data_quality or load_ratio. There is deliberately no
// function anywhere in this file that maps a value to a color -- that
// structurally rules out the red/yellow/green case, rather than relying
// on remembering not to add one.
function PointRow({ point }: { point: TrainingLoadPoint }) {
  return (
    <View style={styles.pointRow}>
      <Text style={styles.pointDate}>{point.date}</Text>
      <Text style={styles.pointDetail}>
        acute {point.acute_load} &middot; chronic {point.chronic_load}
        {point.load_ratio !== null ? ` · ratio ${point.load_ratio.toFixed(2)}` : ''}
      </Text>
      <Text style={styles.pointQuality}>{point.data_quality}</Text>
    </View>
  );
}

export default function TrendScreen() {
  const { request } = useSession();
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [endDate, setEndDate] = useState('');

  const load = useCallback(
    async (explicitEndDate?: string) => {
      setState({ kind: 'loading' });
      try {
        const data = await request((token) => getTrainingLoadTrend(token, explicitEndDate || undefined));
        setState({ kind: 'loaded', data });
      } catch {
        setState({ kind: 'error' });
      }
    },
    [request]
  );

  useFocusEffect(
    useCallback(() => {
      load();
      // Deliberately re-run only on focus, not on every endDate keystroke --
      // the explicit-date fetch is triggered by the "View" button below.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
  );

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Training Load Trend</Text>

      <View style={styles.dateRow}>
        <DateField value={endDate} onChangeText={setEndDate} placeholder="End date (optional)" />
        <Button title="View" onPress={() => load(endDate)} />
      </View>

      {state.kind === 'loading' ? <ActivityIndicator /> : null}

      {state.kind === 'error' ? (
        <View style={styles.centered}>
          <Text style={styles.error}>Could not load the trend.</Text>
          <Button title="Retry" onPress={() => load(endDate)} />
        </View>
      ) : null}

      {state.kind === 'loaded' ? (
        <>
          <Text style={styles.rangeText}>
            {state.data.start_date} &ndash; {state.data.end_date}
          </Text>
          {state.data.series.map((series) => (
            <View key={`${series.unit}-${series.source_metric}`} style={styles.seriesBlock}>
              <Text style={styles.seriesTitle}>
                {series.unit} ({series.source_metric})
              </Text>
              {series.points.map((point) => (
                <PointRow key={point.date} point={point} />
              ))}
            </View>
          ))}
        </>
      ) : null}

      <RestDayControl />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 8 },
  centered: { alignItems: 'center', gap: 8, paddingVertical: 16 },
  title: { fontSize: 22, fontWeight: '700' },
  dateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  rangeText: { color: '#666', marginBottom: 8 },
  seriesBlock: { marginBottom: 16 },
  seriesTitle: { fontSize: 16, fontWeight: '600', marginBottom: 6 },
  pointRow: {
    padding: 10,
    borderRadius: 8,
    backgroundColor: '#f2f2f2',
    marginBottom: 6,
  },
  pointDate: { fontSize: 12, color: '#666' },
  pointDetail: { fontSize: 14, marginTop: 2 },
  pointQuality: { fontSize: 12, color: '#333', marginTop: 2 },
  error: { color: '#c00' },
});
