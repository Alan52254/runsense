import { useCallback, useEffect, useMemo, useState } from 'react';
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
import {
  ApiError,
  CreateInjuryReportInput,
  createInjuryGuidance,
  createInjuryReport,
  getInjuryReports,
  InjuryReportResponse,
  InjuryGuidanceResponse,
  SeverityBand,
} from './api';
import CoachChatModal from './CoachChatModal';
import { generateUuidV4 } from './uuid';
import { HEALTH_COACH_DISCLAIMER } from './healthCoach';

const BODY_PARTS = ['右小腿', '左小腿', '右膝', '左膝', '右足底', '左足底', '阿基里斯腱', '髖／臀', '下背', '其他'];
const SEVERITIES: Exclude<SeverityBand, 'NONE'>[] = ['MILD', 'MODERATE', 'SEVERE'];
const L = 'zh-TW' as const;

type FormState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'ok' }
  | { kind: 'rejected'; message: string }
  | { kind: 'network' };

type HistoryState =
  | { kind: 'loading' }
  | { kind: 'ok'; items: InjuryReportResponse[] }
  | { kind: 'error' };

export default function BodyScreen() {
  const { request } = useSession();
  const insets = useSafeAreaInsets();

  const [hasIssue, setHasIssue] = useState(true);
  const [severity, setSeverity] = useState<Exclude<SeverityBand, 'NONE'>>('MILD');
  const [bodyPart, setBodyPart] = useState(BODY_PARTS[0]);
  const [freeText, setFreeText] = useState('');
  const [mutationId, setMutationId] = useState(() => generateUuidV4());
  const [form, setForm] = useState<FormState>({ kind: 'idle' });
  const [history, setHistory] = useState<HistoryState>({ kind: 'loading' });
  const [chestFlag, setChestFlag] = useState(false);
  const [heatFlag, setHeatFlag] = useState(false);
  const [boneFlag, setBoneFlag] = useState(false);
  const [guidance, setGuidance] = useState<InjuryGuidanceResponse | null>(null);
  const [guidanceLoading, setGuidanceLoading] = useState(false);
  const [coachModalVisible, setCoachModalVisible] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistory({ kind: 'loading' });
    try {
      const res = await request((tok) => getInjuryReports(tok));
      setHistory({ kind: 'ok', items: res.items });
    } catch {
      setHistory({ kind: 'error' });
    }
  }, [request]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  async function submit() {
    setForm({ kind: 'submitting' });
    const input: CreateInjuryReportInput = hasIssue
      ? { clientMutationId: mutationId, hasIssue: true, severityBand: severity, bodyPart, freeText: freeText.trim() || null }
      : { clientMutationId: mutationId, hasIssue: false, severityBand: 'NONE', bodyPart: null, freeText: freeText.trim() || null };
    let report;
    try {
      report = await request((tok) => createInjuryReport(tok, input));
    } catch (err) {
      if (err instanceof ApiError && err.kind === 'network') setForm({ kind: 'network' });
      else if (err instanceof ApiError) setForm({ kind: 'rejected', message: err.message });
      else setForm({ kind: 'rejected', message: 'Something went wrong.' });
      return;
    }

    // The report is persisted. Everything below is best-effort follow-up and
    // must never flip the form back to a failure state.
    setForm({ kind: 'ok' });
    setFreeText('');
    setMutationId(generateUuidV4()); // a fresh report gets a fresh id; a retry of THIS one reuses it
    loadHistory();

    if (hasIssue) {
      setGuidanceLoading(true);
      try {
        const result = await request((tok) =>
          createInjuryGuidance(tok, report.id, {
            chestPainOrBreathingDifficulty: chestFlag,
            collapseConfusionOrExtremeHeatIllness: heatFlag,
            localizedBonePainWorseWithWeightBearing: boneFlag,
          }),
        );
        setGuidance(result);
      } catch {
        setGuidance(null); // guidance is unavailable; the report still went through
      } finally {
        setGuidanceLoading(false);
      }
    }
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 28 }]}
    >
      <Text style={styles.title}>身體狀況 · Body Status</Text>
      <Text style={styles.hint}>
        「有沒有不適／程度」與你寫的文字內容分開儲存，各自套用獨立的授權政策。
      </Text>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>回報身體狀況</Text>

        <View style={styles.segRow}>
          <TouchableOpacity
            style={[styles.seg, hasIssue && styles.segOn]}
            onPress={() => { setHasIssue(true); setMutationId(generateUuidV4()); }}
          >
            <Text style={[styles.segText, hasIssue && styles.segTextOn]}>有不適</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.seg, !hasIssue && styles.segOn]}
            onPress={() => { setHasIssue(false); setMutationId(generateUuidV4()); }}
          >
            <Text style={[styles.segText, !hasIssue && styles.segTextOn]}>沒有不適</Text>
          </TouchableOpacity>
        </View>

        {hasIssue ? (
          <>
            <Text style={styles.label}>程度分級</Text>
            <View style={styles.segRow}>
              {SEVERITIES.map((s) => (
                <TouchableOpacity
                  key={s}
                  style={[styles.seg, severity === s && styles.segOn]}
                  onPress={() => { setSeverity(s); setMutationId(generateUuidV4()); }}
                >
                  <Text style={[styles.segText, severity === s && styles.segTextOn]}>{s}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.label}>部位</Text>
            <View style={styles.chips}>
              {BODY_PARTS.map((p) => (
                <TouchableOpacity
                  key={p}
                  style={[styles.chip, bodyPart === p && styles.chipOn]}
                  onPress={() => { setBodyPart(p); setMutationId(generateUuidV4()); }}
                >
                  <Text style={[styles.chipText, bodyPart === p && styles.chipTextOn]}>{p}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </>
        ) : null}

        <Text style={styles.label}>自述內容（僅你可見，除非另外授權教練）</Text>
        <TextInput
          style={styles.textarea}
          multiline
          placeholder="例如：下樓梯時右小腿內側會緊，走路不痛。"
          value={freeText}
          onChangeText={(t) => { setFreeText(t); }}
        />

        {hasIssue ? (
          <>
            <Text style={styles.label}>需要立即分流的明確狀況（請依實際情況勾選）</Text>
            {[
              ['胸痛或呼吸困難', chestFlag, setChestFlag],
              ['運動中倒下、意識混亂或嚴重熱傷害症狀', heatFlag, setHeatFlag],
              ['局部骨頭疼痛且負重時更痛', boneFlag, setBoneFlag],
            ].map(([label, checked, setter]) => (
              <TouchableOpacity
                key={String(label)}
                style={[styles.flagRow, checked && styles.flagRowOn]}
                onPress={() => (setter as (value: boolean) => void)(!checked)}
              >
                <Text style={styles.flagText}>{checked ? '☑' : '☐'} {String(label)}</Text>
              </TouchableOpacity>
            ))}
          </>
        ) : null}

        {form.kind === 'submitting' ? (
          <ActivityIndicator style={{ marginTop: 12 }} />
        ) : (
          <View style={{ marginTop: 12 }}>
            <Button title="送出回報" onPress={submit} />
          </View>
        )}
        {form.kind === 'ok' ? <Text style={styles.ok}>已送出回報。</Text> : null}
        {form.kind === 'rejected' ? (
          <Text style={styles.err}>伺服器拒絕：{form.message}</Text>
        ) : null}
        {form.kind === 'network' ? (
          <Text style={styles.err}>無法連線，未送出。請確認網路後重試（重試會沿用同一筆識別碼，不會重複建立）。</Text>
        ) : null}
      </View>

      {/* --- Health-coach channel entry point (typed seam) --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>健康教練 · Health coach</Text>
        {guidanceLoading ? (
          <ActivityIndicator />
        ) : guidance ? (
          <>
            <Text style={styles.badge}>{guidance.urgency}</Text>
            <Text style={styles.guidanceSummary}>{guidance.summary}</Text>
            {guidance.next_steps.map((step) => <Text key={step} style={styles.hint}>• {step}</Text>)}
            {guidance.citations.map((citation) => (
              <Text key={citation.evidence_id} style={styles.citation}>
                來源：{citation.publisher} — {citation.title}{'\n'}{citation.source_url}
              </Text>
            ))}
            <Text style={styles.disclaimer}>{guidance.disclaimer}</Text>

            <TouchableOpacity
              style={{
                backgroundColor: '#ea580c',
                paddingVertical: 12,
                paddingHorizontal: 16,
                borderRadius: 10,
                alignItems: 'center',
                marginTop: 12,
              }}
              onPress={() => setCoachModalVisible(true)}
            >
              <Text style={{ color: '#ffffff', fontWeight: 'bold', fontSize: 13.5 }}>
                🏃‍♂️ 向 AI 健康教練深入諮詢（帶入此傷痛報告）
              </Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={styles.disclaimer}>{HEALTH_COACH_DISCLAIMER[L]}</Text>
            <Text style={styles.hint}>送出一筆有不適的身體回報後，系統會先做固定安全分流，再顯示有來源的衛教資訊。</Text>
          </>
        )}
      </View>

      {/* --- Report history --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>回報紀錄</Text>
        {history.kind === 'loading' ? <ActivityIndicator /> : null}
        {history.kind === 'error' ? (
          <View>
            <Text style={styles.err}>暫時無法載入回報紀錄。</Text>
            <TouchableOpacity style={styles.retry} onPress={loadHistory}>
              <Text style={styles.retryText}>重試</Text>
            </TouchableOpacity>
          </View>
        ) : null}
        {history.kind === 'ok' && history.items.length === 0 ? (
          <Text style={styles.hint}>還沒有回報紀錄。</Text>
        ) : null}
        {history.kind === 'ok'
          ? history.items.map((r) => (
              <View key={r.id} style={styles.histRow}>
                <Text style={styles.histDate}>{r.local_training_date}</Text>
                <Text style={styles.histBody}>
                  {r.has_issue
                    ? `${r.body_part ?? '未指定部位'} · ${r.severity_band}`
                    : '回報無不適'}
                </Text>
                {r.free_text ? <Text style={styles.histNote}>{r.free_text}</Text> : null}
              </View>
            ))
          : null}
      </View>

      <CoachChatModal
        visible={coachModalVisible}
        onClose={() => setCoachModalVisible(false)}
        initialBodyPart={bodyPart}
        initialSeverity={severity}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f1f5f9' },
  content: { padding: 16, gap: 14 },
  title: { fontSize: 20, fontWeight: '800', color: '#0f172a' },
  hint: { fontSize: 12.5, color: '#64748b', lineHeight: 18 },
  card: { backgroundColor: '#fff', borderRadius: 14, padding: 16, gap: 8, borderWidth: 1, borderColor: '#e2e8f0' },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#0f172a' },
  label: { fontSize: 12.5, fontWeight: '600', color: '#334155', marginTop: 8 },
  segRow: { flexDirection: 'row', gap: 8, marginTop: 6 },
  seg: { flex: 1, paddingVertical: 9, borderRadius: 8, backgroundColor: '#f1f5f9', alignItems: 'center', borderWidth: 1, borderColor: '#e2e8f0' },
  segOn: { backgroundColor: '#ea580c', borderColor: '#ea580c' },
  segText: { fontSize: 12.5, fontWeight: '600', color: '#475569' },
  segTextOn: { color: '#fff' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  chip: { paddingVertical: 6, paddingHorizontal: 10, borderRadius: 16, backgroundColor: '#f1f5f9', borderWidth: 1, borderColor: '#e2e8f0' },
  chipOn: { backgroundColor: '#0f172a', borderColor: '#0f172a' },
  chipText: { fontSize: 12, color: '#475569' },
  chipTextOn: { color: '#fff' },
  textarea: { borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 10, padding: 10, fontSize: 14, minHeight: 70, marginTop: 4, textAlignVertical: 'top' },
  ok: { color: '#047857', marginTop: 10, fontSize: 13 },
  err: { color: '#dc2626', marginTop: 10, fontSize: 12.5, lineHeight: 18 },
  badge: { alignSelf: 'flex-start', fontSize: 12, fontWeight: '700', color: '#92400e', backgroundColor: '#fef3c7', paddingVertical: 3, paddingHorizontal: 8, borderRadius: 6, overflow: 'hidden' },
  disclaimer: { fontSize: 11.5, color: '#64748b', lineHeight: 16, marginTop: 4 },
  disabledBtn: { marginTop: 8, paddingVertical: 11, borderRadius: 10, alignItems: 'center', backgroundColor: '#f1f5f9', borderWidth: 1, borderColor: '#e2e8f0' },
  disabledBtnText: { fontSize: 13, fontWeight: '600', color: '#94a3b8' },
  retry: { alignSelf: 'flex-start', marginTop: 8, paddingVertical: 6, paddingHorizontal: 12, backgroundColor: '#f1f5f9', borderRadius: 8, borderWidth: 1, borderColor: '#cbd5e1' },
  retryText: { fontSize: 12, fontWeight: '600', color: '#334155' },
  histRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: '#f1f5f9' },
  histDate: { fontSize: 11, color: '#94a3b8' },
  histBody: { fontSize: 13, color: '#1e293b', marginTop: 2 },
  histNote: { fontSize: 12, color: '#64748b', marginTop: 3, lineHeight: 17 },
  flagRow: { padding: 9, borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 8, marginTop: 4 },
  flagRowOn: { backgroundColor: '#fff7ed', borderColor: '#ea580c' },
  flagText: { fontSize: 12.5, color: '#334155' },
  guidanceSummary: { fontSize: 15, fontWeight: '700', color: '#7f1d1d', lineHeight: 22 },
  citation: { fontSize: 11, color: '#475569', lineHeight: 16, marginTop: 5 },
});
