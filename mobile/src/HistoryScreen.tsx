import { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { ActivityIndicator, Button, FlatList, StyleSheet, Text, View } from 'react-native';
import { ActivityResponse, getActivityHistory } from './api';
import { useSession } from './SessionContext';

type LoadState =
  | { kind: 'loading' }
  | { kind: 'loaded'; items: ActivityResponse[]; nextCursor: string | null; loadingMore: boolean }
  | { kind: 'error' };

const PAGE_SIZE = 20;

export default function HistoryScreen() {
  const { request } = useSession();
  const [state, setState] = useState<LoadState>({ kind: 'loading' });

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
      renderItem={({ item }) => (
        <View style={styles.row}>
          <Text style={styles.rowDate}>{item.local_training_date}</Text>
          <Text style={styles.rowDetail}>
            {item.duration_minutes} min &middot; RPE {item.rpe}
          </Text>
          <Text style={styles.rowLoad}>
            {item.session_load} {item.unit}
          </Text>
        </View>
      )}
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
  list: { padding: 16 },
  row: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: '#f2f2f2',
    marginBottom: 8,
  },
  rowDate: { fontSize: 12, color: '#666' },
  rowDetail: { fontSize: 16, marginTop: 2 },
  rowLoad: { fontSize: 14, color: '#1a7a34', marginTop: 4, fontWeight: '600' },
  footer: { paddingVertical: 16, alignItems: 'center' },
  error: { color: '#c00' },
  emptyText: { color: '#666', fontSize: 16 },
});
