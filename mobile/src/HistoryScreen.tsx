import { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { ActivityIndicator, Button, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ActivityResponse, getActivityHistory } from './api';
import { useSession } from './SessionContext';
import { buildActivityMetricRows } from './activityMetrics';
import { colors, radius, space } from './theme';

type LoadState =
  | { kind: 'loading' }
  | { kind: 'loaded'; items: ActivityResponse[]; nextCursor: string | null; loadingMore: boolean }
  | { kind: 'error' };

const PAGE_SIZE = 20;

export default function HistoryScreen() {
  const { request } = useSession();
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const page = await request((token) => getActivityHistory(token, { limit: PAGE_SIZE }));
      setState({ kind: 'loaded', items: page.items, nextCursor: page.next_cursor, loadingMore: false });
    } catch {
      setState({ kind: 'error' });
    }
  }, [request]);

  // Refetch whenever this tab gains focus, per design.md Decision 4 --
  // no shared cache/invalidation event bus, just refetch on focus.
  useFocusEffect(
    useCallback(() => {
      loadFirstPage();
    }, [loadFirstPage])
  );

  async function loadMore() {
    if (state.kind !== 'loaded' || state.nextCursor === null || state.loadingMore) return;
    const cursor = state.nextCursor;
    setState({ ...state, loadingMore: true });
    try {
      const page = await request((token) =>
        getActivityHistory(token, { limit: PAGE_SIZE, cursor })
      );
      setState((prev) =>
        prev.kind === 'loaded'
          ? {
              kind: 'loaded',
              items: [...prev.items, ...page.items],
              nextCursor: page.next_cursor,
              loadingMore: false,
            }
          : prev
      );
    } catch {
      setState((prev) => (prev.kind === 'loaded' ? { ...prev, loadingMore: false } : prev));
    }
  }

  if (state.kind === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator />
      </View>
    );
  }

  if (state.kind === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.error}>Could not load history.</Text>
        <Button title="Retry" onPress={loadFirstPage} />
      </View>
    );
  }

  if (state.items.length === 0) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyText}>No activities logged yet.</Text>
      </View>
    );
  }

  return (
    <FlatList
      contentContainerStyle={styles.list}
      data={state.items}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => {
        const metrics = buildActivityMetricRows(item.device_metrics ?? {});
        const expanded = expandedId === item.id;
        return (
          <Pressable
            style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
            onPress={() => setExpandedId(expanded ? null : item.id)}
            accessibilityRole="button"
            accessibilityLabel={`${item.local_training_date} 跑步紀錄，${expanded ? '收合' : '展開'}詳細資料`}
            accessibilityState={{ expanded }}
          >
            <View style={styles.rowHead}>
              <View>
                <Text style={styles.rowDate}>{item.local_training_date} · {item.provider.toUpperCase()}</Text>
                <Text style={styles.rowDetail}>{item.duration_minutes} 分鐘 · {item.distance_km ?? '—'} km</Text>
              </View>
              <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={20} color={colors.inkMuted} />
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.rowLoad}>{item.session_load} {item.unit}</Text>
              <Text style={styles.rpe}>RPE {item.rpe ?? '—'}</Text>
            </View>
            {expanded ? (
              <View style={styles.metrics}>
                {metrics.length ? metrics.map((metric) => (
                  <View key={metric.label} style={styles.metric}>
                    <Text style={styles.metricLabel}>{metric.label}</Text>
                    <Text style={styles.metricValue}>{metric.value}</Text>
                  </View>
                )) : <Text style={styles.emptyMetric}>此筆紀錄沒有裝置生理指標。</Text>}
              </View>
            ) : null}
          </Pressable>
        );
      }}
      ListFooterComponent={
        state.nextCursor ? (
          <View style={styles.footer}>
            {state.loadingMore ? (
              <ActivityIndicator />
            ) : (
              <Button title="Load more" onPress={loadMore} />
            )}
          </View>
        ) : null
      }
    />
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24, gap: 12 },
  list: { padding: space.md, backgroundColor: colors.canvas },
  row: {
    padding: space.md, borderRadius: radius.lg, backgroundColor: colors.surface,
    marginBottom: space.sm, borderWidth: 1, borderColor: colors.border,
  },
  rowPressed: { backgroundColor: colors.surfaceMuted, borderColor: colors.accent },
  rowHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  rowDate: { fontSize: 12, color: colors.inkSubtle, fontWeight: '600' },
  rowDetail: { fontSize: 17, marginTop: 4, color: colors.ink, fontWeight: '700' },
  summaryRow: { flexDirection: 'row', gap: 12, marginTop: 10 },
  rowLoad: { fontSize: 13, color: colors.safe, fontWeight: '700', backgroundColor: colors.safeSoft, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill },
  rpe: { fontSize: 13, color: colors.inkMuted, paddingVertical: 4 },
  metrics: { marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  metric: { width: '48%', padding: 10, borderRadius: radius.md, backgroundColor: colors.surfaceMuted },
  metricLabel: { fontSize: 11, color: colors.inkSubtle },
  metricValue: { fontSize: 14, color: colors.ink, fontWeight: '700', marginTop: 3 },
  emptyMetric: { color: colors.inkSubtle, fontSize: 13 },
  footer: { paddingVertical: 16, alignItems: 'center' },
  error: { color: '#c00' },
  emptyText: { color: '#666', fontSize: 16 },
});
