import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSession } from './SessionContext';
import { createActivity } from './api';

export default function LiveRunScreen({ navigation }: { navigation: any }) {
  const { request } = useSession();
  const [phase, setPhase] = useState<'idle' | 'running' | 'paused' | 'finished'>('idle');
  const [elapsedSec, setElapsedSec] = useState(0);
  const [targetPaceSec, setTargetPaceSec] = useState(330); // 5:30/km
  const [rpe, setRpe] = useState(5);
  const [saving, setSaving] = useState(false);
  const [rpeModalVisible, setRpeModalVisible] = useState(false);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Derived live telemetry
  const distanceKm = Number(((elapsedSec / Math.max(targetPaceSec, 60))).toFixed(2));
  const cadenceSpm = phase === 'running' ? Math.round(176 + Math.sin(elapsedSec / 10) * 4) : 0;
  const caloriesKcal = Math.round(distanceKm * 65);
  const currentHr = phase === 'running' ? Math.round(145 + Math.sin(elapsedSec / 20) * 8) : 0;

  // HR Zone: 1 (<120), 2 (120-140), 3 (140-160), 4 (160-175), 5 (>175)
  function getHrZone(hr: number) {
    if (hr < 120) return { zone: 1, label: 'Z1 恢復' };
    if (hr < 140) return { zone: 2, label: 'Z2 有氧' };
    if (hr < 160) return { zone: 3, label: 'Z3 節奏' };
    if (hr < 175) return { zone: 4, label: 'Z4 閾值' };
    return { zone: 5, label: 'Z5 極限' };
  }
  const hrZoneInfo = getHrZone(currentHr);

  // 1km splits
  const completedKms = Math.floor(distanceKm);
  const splits = Array.from({ length: completedKms }, (_, i) => ({
    km: i + 1,
    pace: formatPace(targetPaceSec),
    duration: formatDuration((i + 1) * targetPaceSec),
  }));

  useEffect(() => {
    if (phase === 'running') {
      timerRef.current = setInterval(() => {
        setElapsedSec((prev) => prev + 1);
      }, 1000);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [phase]);

  function formatDuration(totalSec: number) {
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function formatPace(sec: number) {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}'${String(s).padStart(2, '0')}"`;
  }

  function handleStart() {
    setPhase('running');
  }

  function handlePause() {
    setPhase('paused');
  }

  function handleResume() {
    setPhase('running');
  }

  function handleStop() {
    setPhase('paused');
    setRpeModalVisible(true);
  }

  async function handleSaveRun() {
    setSaving(true);
    try {
      const durationMinutes = Math.max(1, Math.round(elapsedSec / 60));
      await request((token) => createActivity(token, {
        durationMinutes,
        rpe,
      }));
      setRpeModalVisible(false);
      Alert.alert('跑步結算成功', '已為你記錄本次跑步並存入體能數據！', [
        { text: '回今日訓練', onPress: () => navigation.navigate('Today') },
      ]);
      setPhase('idle');
      setElapsedSec(0);
    } catch (e: any) {
      Alert.alert('儲存失敗', e.message || '請確認網路狀態後再試。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
      {/* Top Banner Status */}
      <View style={[styles.statusPill, phase === 'running' && styles.statusPillActive]}>
        <View style={[styles.statusDot, phase === 'running' && styles.statusDotActive]} />
        <Text style={[styles.statusText, phase === 'running' && styles.statusTextActive]}>
          {phase === 'idle' && '準備開跑 · LACE UP & GO'}
          {phase === 'running' && '即時跑步追蹤中 · RUNNING'}
          {phase === 'paused' && '跑步暫停 · WORKOUT PAUSED'}
        </Text>
      </View>

      {/* Main Massive Athletic Timer */}
      <View style={styles.timerCard}>
        <Text style={styles.timerDigits}>{formatDuration(elapsedSec)}</Text>
        <Text style={styles.timerLabel}>經過時間 ELAPSED TIME</Text>
      </View>

      {/* 4-Stat Primary Telemetry HUD */}
      <View style={styles.hudGrid}>
        <View style={styles.hudTile}>
          <Text style={styles.hudLabel}>累積里程</Text>
          <Text style={styles.hudVal}>{distanceKm.toFixed(2)}</Text>
          <Text style={styles.hudUnit}>公里 KM</Text>
        </View>

        <View style={styles.hudTile}>
          <Text style={styles.hudLabel}>即時配速</Text>
          <Text style={styles.hudVal}>{formatPace(targetPaceSec)}</Text>
          <Text style={styles.hudUnit}>/公里 /KM</Text>
        </View>

        <View style={styles.hudTile}>
          <Text style={styles.hudLabel}>即時步頻</Text>
          <Text style={styles.hudVal}>{cadenceSpm}</Text>
          <Text style={styles.hudUnit}>SPM</Text>
        </View>

        <View style={styles.hudTile}>
          <Text style={styles.hudLabel}>估算消耗</Text>
          <Text style={styles.hudVal}>{caloriesKcal}</Text>
          <Text style={styles.hudUnit}>千卡 KCAL</Text>
        </View>
      </View>

      {/* Heart Rate & 5-Zone Gauge */}
      <View style={styles.hrCard}>
        <View style={styles.hrHeader}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Ionicons name="heart" size={18} color="#ef4444" />
            <Text style={styles.hrTitle}>心率區間 (HR ZONE)</Text>
          </View>
          <Text style={styles.hrBpmText}>{currentHr} <Text style={{ fontSize: 12 }}>BPM</Text></Text>
        </View>

        {/* 5-Segment Visualizer */}
        <View style={styles.hrZoneBarRow}>
          {[1, 2, 3, 4, 5].map((z) => (
            <View
              key={z}
              style={[
                styles.hrSegment,
                hrZoneInfo.zone >= z && styles.hrSegmentActive,
                hrZoneInfo.zone === z && { backgroundColor: '#ea580c' },
              ]}
            />
          ))}
        </View>
        <Text style={styles.hrZoneLabel}>{hrZoneInfo.label}</Text>
      </View>

      {/* 1km Splits List (if any completed) */}
      {splits.length > 0 && (
        <View style={styles.splitsCard}>
          <Text style={styles.splitsTitle}>每公里分段 (Kilometer Splits)</Text>
          {splits.map((s) => (
            <View key={s.km} style={styles.splitRow}>
              <Text style={styles.splitKm}>第 {s.km} 公里</Text>
              <Text style={styles.splitPace}>{s.pace}</Text>
              <Text style={styles.splitDuration}>{s.duration}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Controller Buttons */}
      <View style={styles.controlRow}>
        {phase === 'idle' && (
          <TouchableOpacity style={styles.startBtn} onPress={handleStart}>
            <Ionicons name="play" size={24} color="#ffffff" />
            <Text style={styles.startBtnText}>開始今日訓練</Text>
          </TouchableOpacity>
        )}

        {phase === 'running' && (
          <>
            <TouchableOpacity style={styles.pauseBtn} onPress={handlePause}>
              <Ionicons name="pause" size={20} color="#0f172a" />
              <Text style={styles.pauseBtnText}>暫停</Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.stopBtn} onPress={handleStop}>
              <Ionicons name="stop" size={20} color="#ffffff" />
              <Text style={styles.stopBtnText}>結束結算</Text>
            </TouchableOpacity>
          </>
        )}

        {phase === 'paused' && (
          <>
            <TouchableOpacity style={styles.resumeBtn} onPress={handleResume}>
              <Ionicons name="play" size={20} color="#ffffff" />
              <Text style={styles.resumeBtnText}>繼續</Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.stopBtn} onPress={handleStop}>
              <Ionicons name="checkmark" size={20} color="#ffffff" />
              <Text style={styles.stopBtnText}>完成並結算</Text>
            </TouchableOpacity>
          </>
        )}
      </View>

      {/* RPE Modal on Finish */}
      <Modal visible={rpeModalVisible} transparent animationType="slide">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>評定自覺疲勞強度 (RPE)</Text>
            <Text style={styles.modalDesc}>
              本次共跑 {formatDuration(elapsedSec)}（約 {distanceKm} km），請為本次跑步的疲勞程度打分：
            </Text>

            <View style={styles.rpeGrid}>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((num) => (
                <TouchableOpacity
                  key={num}
                  style={[styles.rpeBtn, rpe === num && styles.rpeBtnActive]}
                  onPress={() => setRpe(num)}
                >
                  <Text style={[styles.rpeBtnText, rpe === num && styles.rpeBtnTextActive]}>
                    {num}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.rpeHint}>目前強度：RPE {rpe}（1 最輕鬆 ~ 10 最極限）</Text>

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.modalSaveBtn}
                onPress={handleSaveRun}
                disabled={saving}
              >
                <Text style={styles.modalSaveText}>{saving ? '儲存中…' : '確認儲存並完成'}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.modalCancelBtn}
                onPress={() => setRpeModalVisible(false)}
              >
                <Text style={styles.modalCancelText}>取消返回</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f172a' },
  scrollContent: { padding: 18, paddingBottom: 40 },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'center',
    gap: 8,
    backgroundColor: '#1e293b',
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 20,
    marginBottom: 16,
  },
  statusPillActive: { backgroundColor: '#14532d' },
  statusDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#64748b' },
  statusDotActive: { backgroundColor: '#22c55e' },
  statusText: { fontSize: 11.5, fontWeight: '700', color: '#94a3b8', letterSpacing: 0.5 },
  statusTextActive: { color: '#86efac' },
  timerCard: { alignItems: 'center', marginVertical: 12 },
  timerDigits: { fontSize: 62, fontWeight: '800', color: '#ffffff', fontVariant: ['tabular-nums'] },
  timerLabel: { fontSize: 11, fontWeight: '600', color: '#64748b', marginTop: 4, letterSpacing: 1 },
  hudGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginVertical: 14 },
  hudTile: { flex: 1, minWidth: '45%', backgroundColor: '#1e293b', padding: 14, borderRadius: 14 },
  hudLabel: { fontSize: 11, fontWeight: '600', color: '#94a3b8', marginBottom: 4 },
  hudVal: { fontSize: 26, fontWeight: '800', color: '#ffffff' },
  hudUnit: { fontSize: 11, color: '#64748b', marginTop: 2 },
  hrCard: { backgroundColor: '#1e293b', padding: 16, borderRadius: 14, marginBottom: 14 },
  hrHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  hrTitle: { fontSize: 12, fontWeight: '700', color: '#94a3b8' },
  hrBpmText: { fontSize: 18, fontWeight: '800', color: '#ef4444' },
  hrZoneBarRow: { flexDirection: 'row', gap: 4, height: 8, marginBottom: 6 },
  hrSegment: { flex: 1, backgroundColor: '#334155', borderRadius: 4 },
  hrSegmentActive: { backgroundColor: '#f97316' },
  hrZoneLabel: { fontSize: 12, color: '#94a3b8', textAlign: 'right', fontWeight: '600' },
  splitsCard: { backgroundColor: '#1e293b', padding: 14, borderRadius: 14, marginBottom: 14 },
  splitsTitle: { fontSize: 13, fontWeight: '700', color: '#ffffff', marginBottom: 10 },
  splitRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: '#334155' },
  splitKm: { color: '#e2e8f0', fontSize: 13, fontWeight: '600' },
  splitPace: { color: '#38bdf8', fontSize: 13, fontWeight: '700' },
  splitDuration: { color: '#94a3b8', fontSize: 13 },
  controlRow: { flexDirection: 'row', gap: 10, marginTop: 10 },
  startBtn: { flex: 1, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 8, backgroundColor: '#ea580c', paddingVertical: 16, borderRadius: 14 },
  startBtnText: { color: '#ffffff', fontSize: 17, fontWeight: '800' },
  pauseBtn: { flex: 1, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6, backgroundColor: '#ffffff', paddingVertical: 14, borderRadius: 14 },
  pauseBtnText: { color: '#0f172a', fontSize: 15, fontWeight: '700' },
  resumeBtn: { flex: 1, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6, backgroundColor: '#16a34a', paddingVertical: 14, borderRadius: 14 },
  resumeBtnText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  stopBtn: { flex: 1, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6, backgroundColor: '#dc2626', paddingVertical: 14, borderRadius: 14 },
  stopBtnText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  modalContent: { backgroundColor: '#ffffff', borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24 },
  modalTitle: { fontSize: 20, fontWeight: '800', color: '#0f172a', marginBottom: 8 },
  modalDesc: { fontSize: 13.5, color: '#64748b', lineHeight: 20, marginBottom: 16 },
  rpeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  rpeBtn: { width: 44, height: 44, borderRadius: 10, backgroundColor: '#f1f5f9', justifyContent: 'center', alignItems: 'center' },
  rpeBtnActive: { backgroundColor: '#ea580c' },
  rpeBtnText: { fontSize: 16, fontWeight: '700', color: '#0f172a' },
  rpeBtnTextActive: { color: '#ffffff' },
  rpeHint: { fontSize: 12.5, color: '#ea580c', fontWeight: '600', marginBottom: 18 },
  modalActions: { gap: 10 },
  modalSaveBtn: { backgroundColor: '#ea580c', paddingVertical: 14, borderRadius: 12, alignItems: 'center' },
  modalSaveText: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
  modalCancelBtn: { paddingVertical: 10, alignItems: 'center' },
  modalCancelText: { color: '#64748b', fontSize: 14 },
});
