import { useState } from 'react';
import {
  ActivityIndicator,
  Button,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ActivityResponse, ApiError, createActivity } from './api';
import { useSession } from './SessionContext';

// Manual log of a past / offline-completed workout. Replaces the bare
// EntryScreen. Shows the SERVER-returned session_load, never a value
// recomputed on-device (design.md Decision 3, carried over).
type SubmitState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'success'; activity: ActivityResponse }
  | { kind: 'rejected'; message: string }
  | { kind: 'network-error' };

export default function LogWorkoutScreen() {
  const { request } = useSession();
  const insets = useSafeAreaInsets();
  const [durationMinutes, setDurationMinutes] = useState('');
  const [rpe, setRpe] = useState('');
  const [state, setState] = useState<SubmitState>({ kind: 'idle' });

  const durationValid = /^\d+$/.test(durationMinutes) && Number(durationMinutes) > 0;
  const rpeValid = /^\d+$/.test(rpe) && Number(rpe) >= 1 && Number(rpe) <= 10;

  async function handleSubmit() {
    setState({ kind: 'submitting' });
    try {
      const activity = await request((token) =>
        createActivity(token, { durationMinutes: Number(durationMinutes), rpe: Number(rpe) })
      );
      setState({ kind: 'success', activity });
    } catch (err) {
      if (err instanceof ApiError && err.kind === 'network') setState({ kind: 'network-error' });
      else if (err instanceof ApiError) setState({ kind: 'rejected', message: err.message });
      else setState({ kind: 'rejected', message: 'Something went wrong.' });
    }
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 24 }]}
    >
      <Text style={styles.title}>手動補登 · Log a Workout</Text>
      <Text style={styles.hint}>
        補登過去或離線完成的訓練。負荷（AU）由伺服器計算：時長 × RPE。
      </Text>

      <Text style={styles.label}>時長（分鐘） · Duration (minutes)</Text>
      <TextInput
        style={styles.input}
        placeholder="45"
        keyboardType="number-pad"
        value={durationMinutes}
        onChangeText={setDurationMinutes}
      />

      <Text style={styles.label}>RPE (1–10)</Text>
      <TextInput
        style={styles.input}
        placeholder="6"
        keyboardType="number-pad"
        value={rpe}
        onChangeText={setRpe}
      />

      {state.kind === 'submitting' ? (
        <ActivityIndicator style={{ marginTop: 16 }} />
      ) : (
        <View style={{ marginTop: 16 }}>
          <Button title="儲存 · Save" onPress={handleSubmit} disabled={!durationValid || !rpeValid} />
        </View>
      )}

      {state.kind === 'success' ? (
        <View style={styles.okBox}>
          <Text style={styles.okLabel}>已儲存 · Saved. Session load (server-computed):</Text>
          <Text style={styles.okValue}>
            {state.activity.session_load} {state.activity.unit}
          </Text>
          <Text style={styles.okFoot}>{state.activity.local_training_date}</Text>
        </View>
      ) : null}

      {state.kind === 'rejected' ? (
        <Text style={styles.error}>伺服器拒絕 · Rejected: {state.message}</Text>
      ) : null}

      {state.kind === 'network-error' ? (
        <Text style={styles.error}>
          無法連線，未儲存 · Could not reach the server — the entry was NOT saved. Check your
          connection and try again.
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f8fafc' },
  content: { padding: 20, gap: 4 },
  title: { fontSize: 20, fontWeight: '800', color: '#0f172a', marginBottom: 4 },
  hint: { fontSize: 13, color: '#64748b', marginBottom: 12, lineHeight: 18 },
  label: { fontSize: 13, fontWeight: '600', color: '#334155', marginTop: 12 },
  input: {
    borderWidth: 1,
    borderColor: '#cbd5e1',
    backgroundColor: '#ffffff',
    borderRadius: 10,
    padding: 12,
    fontSize: 16,
    marginTop: 4,
  },
  okBox: { marginTop: 20, padding: 16, borderRadius: 12, backgroundColor: '#ecfdf5', alignItems: 'center' },
  okLabel: { fontSize: 13, color: '#065f46' },
  okValue: { fontSize: 28, fontWeight: '800', color: '#047857', marginTop: 4 },
  okFoot: { fontSize: 12, color: '#059669', marginTop: 4 },
  error: { color: '#dc2626', marginTop: 14, fontSize: 13, lineHeight: 19 },
});
