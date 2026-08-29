import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Button,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSession } from './SessionContext';
import { ActivityResponse, ApiError, createActivity } from './api';
import { formatElapsed } from './format';

// Single-device manual timer. NO GPS (REQ-SCOPE-001) -- distance / pace /
// heart rate are typed in by the athlete. Finishing produces exactly one
// Completed Activity; a failed save keeps the athlete on the summary with
// their data intact.
type Phase = 'idle' | 'running' | 'summary';
type SaveState =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'saved'; activity: ActivityResponse }
  | { kind: 'rejected'; message: string }
  | { kind: 'network' };

export default function LiveRunScreen({ navigation }: { navigation: any }) {
  const { request } = useSession();
  const insets = useSafeAreaInsets();
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [distanceKm, setDistanceKm] = useState('');
  const [avgPace, setAvgPace] = useState('');
  const [heartRate, setHeartRate] = useState('');
  const [rpe, setRpe] = useState('');
  const [save, setSave] = useState<SaveState>({ kind: 'idle' });
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (phase === 'running') {
      timer.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
    };
  }, [phase]);

  const durationMinutes = Math.max(1, Math.round(elapsed / 60));
  const rpeValid = /^\d+$/.test(rpe) && Number(rpe) >= 1 && Number(rpe) <= 10;

  async function finishSave() {
    if (!rpeValid) return;
    setSave({ kind: 'saving' });
    try {
      const activity = await request((tok) =>
        createActivity(tok, { durationMinutes, rpe: Number(rpe) })
      );
      setSave({ kind: 'saved', activity });
    } catch (err) {
      if (err instanceof ApiError && err.kind === 'network') setSave({ kind: 'network' });
      else if (err instanceof ApiError) setSave({ kind: 'rejected', message: err.message });
      else setSave({ kind: 'rejected', message: 'Something went wrong.' });
    }
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 28 }]}
    >
      <Text style={styles.title}>出發開跑！· Live Run</Text>
      <Text style={styles.hint}>Phase 1 無 GPS，距離／配速／心率由你手動輸入。</Text>

      <View style={styles.timerCard}>
        <Text style={styles.timer}>{formatElapsed(elapsed)}</Text>
        <Text style={styles.timerFoot}>約 {durationMinutes} 分鐘</Text>
      </View>

      {phase === 'idle' ? (
        <Button title="開始" onPress={() => setPhase('running')} />
      ) : null}
      {phase === 'running' ? (
        <View style={styles.rowBtns}>
          <TouchableOpacity style={[styles.btn, styles.btnStop]} onPress={() => setPhase('summary')}>
            <Text style={styles.btnStopText}>結束訓練</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {phase !== 'idle' ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>本次數據（手動輸入）</Text>
          <Field label="距離 (km)" value={distanceKm} onChangeText={setDistanceKm} placeholder="7.2" />
          <Field label="平均配速 (m'ss / km，僅記錄)" value={avgPace} onChangeText={setAvgPace} placeholder="5'30" />
          <Field label="平均心率 (bpm)" value={heartRate} onChangeText={setHeartRate} placeholder="148" />
        </View>
      ) : null}

      {phase === 'summary' ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>評定 RPE 並儲存</Text>
          <Text style={styles.hint}>
            儲存後會建立一筆已完成活動；負荷 = 時長 × RPE，由伺服器計算。距離／配速／心率僅供你檢視，不影響負荷。
          </Text>
          <Field label="RPE (1–10)" value={rpe} onChangeText={setRpe} placeholder="6" />

          {save.kind === 'saving' ? (
            <ActivityIndicator style={{ marginTop: 12 }} />
          ) : (
            <View style={{ marginTop: 12 }}>
              <Button title="儲存訓練" onPress={finishSave} disabled={!rpeValid} />
            </View>
          )}

          {save.kind === 'saved' ? (
            <View style={styles.okBox}>
              <Text style={styles.okLabel}>已儲存 · Session load（伺服器計算）</Text>
              <Text style={styles.okValue}>
                {save.activity.session_load} {save.activity.unit}
              </Text>
              <TouchableOpacity style={styles.retry} onPress={() => navigation.navigate('Tabs', { screen: 'History' })}>
                <Text style={styles.retryText}>查看歷程</Text>
              </TouchableOpacity>
            </View>
          ) : null}
          {save.kind === 'rejected' ? (
            <Text style={styles.err}>伺服器拒絕：{save.message}。你的數據仍保留，可再試一次。</Text>
          ) : null}
          {save.kind === 'network' ? (
            <Text style={styles.err}>
              無法連線，尚未儲存。你的數據仍保留在此畫面，請確認網路後再按「儲存訓練」。
            </Text>
          ) : null}
        </View>
      ) : null}
    </ScrollView>
  );
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
}: {
  label: string;
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
}) {
  return (
    <View style={{ marginTop: 8 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        keyboardType="numbers-and-punctuation"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f1f5f9' },
  content: { padding: 16, gap: 14 },
  title: { fontSize: 20, fontWeight: '800', color: '#0f172a' },
  hint: { fontSize: 12.5, color: '#64748b', lineHeight: 18 },
  timerCard: { backgroundColor: '#0f172a', borderRadius: 16, paddingVertical: 28, alignItems: 'center' },
  timer: { fontSize: 48, fontWeight: '800', color: '#fff', fontVariant: ['tabular-nums'] },
  timerFoot: { fontSize: 13, color: '#94a3b8', marginTop: 4 },
  rowBtns: { flexDirection: 'row', gap: 10 },
  btn: { flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: 'center' },
  btnStop: { backgroundColor: '#dc2626' },
  btnStopText: { color: '#fff', fontWeight: '800', fontSize: 15 },
  card: { backgroundColor: '#fff', borderRadius: 14, padding: 16, gap: 4, borderWidth: 1, borderColor: '#e2e8f0' },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#0f172a' },
  label: { fontSize: 12.5, fontWeight: '600', color: '#334155' },
  input: { borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 10, padding: 11, fontSize: 15, marginTop: 4, backgroundColor: '#fff' },
  okBox: { marginTop: 14, padding: 14, borderRadius: 12, backgroundColor: '#ecfdf5', alignItems: 'center' },
  okLabel: { fontSize: 12.5, color: '#065f46' },
  okValue: { fontSize: 26, fontWeight: '800', color: '#047857', marginTop: 4 },
  err: { color: '#dc2626', marginTop: 12, fontSize: 12.5, lineHeight: 18 },
  retry: { marginTop: 10, paddingVertical: 6, paddingHorizontal: 12, backgroundColor: '#f1f5f9', borderRadius: 8, borderWidth: 1, borderColor: '#cbd5e1' },
  retryText: { fontSize: 12, fontWeight: '600', color: '#334155' },
});
