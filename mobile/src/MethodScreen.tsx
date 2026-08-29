import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSession } from './SessionContext';
import {
  getPlanModelReport,
  getTrainingPlanToday,
  PlanModelReportResponse,
  TrainingPlanResponse,
} from './api';

type Section<T> = { status: 'loading' } | { status: 'ok'; data: T } | { status: 'error' };

const TYPE_LABEL: Record<string, string> = {
  REST_AND_SEEK_CARE: '休息並尋求評估',
  REST_DAY: '休息日',
  RECOVERY_RUN: '恢復跑',
  EASY_RUN: '輕鬆跑',
  STEADY_RUN: '穩定跑',
};
const REASON_LABEL: Record<string, string> = {
  LOAD_ELEVATED_FAVOR_RECOVERY: '近期負荷偏高，偏好較輕的訓練',
  LOAD_REDUCED_ADD_STIMULUS: '近期負荷偏低，可加入適度刺激',
  STEADY_STATE: '負荷穩定，維持一般有氧訓練',
  SELF_CARE_LIMIT_INTENSITY: '自我照護分流，限制強度',
  TRIAGE_BLOCKED: '安全分流暫不建議跑步',
  COLD_START_ABSTAIN: '觀測資料不足，改用保守排序',
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.kv}>
      <Text style={styles.kvKey}>{label}</Text>
      <Text style={styles.kvVal}>{value}</Text>
    </View>
  );
}

export default function MethodScreen() {
  const { request } = useSession();
  const insets = useSafeAreaInsets();
  const [plan, setPlan] = useState<Section<TrainingPlanResponse>>({ status: 'loading' });
  const [report, setReport] = useState<Section<PlanModelReportResponse>>({ status: 'loading' });

  const load = useCallback(async () => {
    const [p, r] = await Promise.allSettled([
      request((t) => getTrainingPlanToday(t)),
      request((t) => getPlanModelReport(t)),
    ]);
    setPlan(p.status === 'fulfilled' ? { status: 'ok', data: p.value } : { status: 'error' });
    setReport(r.status === 'fulfilled' ? { status: 'ok', data: r.value } : { status: 'error' });
  }, [request]);

  useEffect(() => {
    load();
  }, [load]);

  const agg = report.status === 'ok' ? report.data.evaluation.baseline_aggregate : undefined;
  const feat = report.status === 'ok' ? report.data.athlete_features : undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 28 }]}
    >
      <Text style={styles.intro}>
        這一頁把每個數字攤開：用了哪個演算法、什麼門檻、以及背後的實證來源。所有推論都在後端完成，個資與 GPS
        不會送往外部生成式服務。
      </Text>

      {/* 1. Plan ranker */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>智慧課表決策（規則式排序）</Text>
        <Text style={styles.hint}>
          候選課表來自審核過的固定模板；排序器只能「重新排序」，不能新增或改動距離、時間、強度（ADR 0002）。
        </Text>
        {plan.status === 'loading' ? <ActivityIndicator /> : null}
        {plan.status === 'error' ? <Text style={styles.err}>暫時無法載入課表決策。</Text> : null}
        {plan.status === 'ok' ? (
          <>
            <Row label="排序理由" value={REASON_LABEL[plan.data.reason_code] ?? plan.data.reason_code} />
            <Row
              label="決策信心"
              value={plan.data.confidence === null ? '—（保守回退）' : `${Math.round(plan.data.confidence * 100)}%`}
            />
            <View style={styles.divider} />
            {plan.data.candidates.map((c, i) => (
              <View key={c.candidate_id} style={styles.candRow}>
                <Text style={[styles.candName, i === 0 && { fontWeight: '700' }]}>
                  {i === 0 ? '▸ ' : ''}
                  {TYPE_LABEL[c.workout_type] ?? c.workout_type}
                  {c.duration_minutes > 0 ? `　${c.duration_minutes} 分` : ''}
                </Text>
                <Text style={styles.candScore}>{c.score === null ? '—' : c.score.toFixed(2)}</Text>
              </View>
            ))}
            {plan.data.candidates[0]?.rationale?.length ? (
              <Text style={styles.hint}>理由：{plan.data.candidates[0].rationale.join('；')}</Text>
            ) : null}
            <View style={styles.divider} />
            <Row label="短長期負荷比" value={String(plan.data.inputs.acute_chronic_ratio ?? '—')} />
            <Row label="觀測天數" value={String(plan.data.inputs.observation_days)} />
            <Row
              label="氣溫 / 狀態"
              value={`${plan.data.inputs.temperature_c === null ? '—' : plan.data.inputs.temperature_c.toFixed(1) + '°C'} (${plan.data.inputs.weather_state})`}
            />
            <Row label="安全分流" value={plan.data.inputs.triage_urgency ?? '無'} />
            <Text style={styles.hint}>
              特徵涵蓋：負荷 {plan.data.feature_coverage.training_load ? '✓' : '✕'}／天氣{' '}
              {plan.data.feature_coverage.weather ? '✓' : '✕'}／傷勢{' '}
              {plan.data.feature_coverage.injury_triage ? '✓' : '✕'} · {plan.data.ranker_version}
            </Text>
          </>
        ) : null}
      </View>

      {/* 2. Offline model evaluation + your-data predictions */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>課表排序模型評估（離線、防資料洩漏）</Text>
        <Text style={styles.hint}>
          後端 backend/ml 內建離線評估：時間向前、以運動員分組、留間隔的切分，回報校準度與涵蓋率。生產環境仍使用規則式排序（ADR
          0002）。
        </Text>
        {report.status === 'loading' ? <ActivityIndicator /> : null}
        {report.status === 'error' ? <Text style={styles.err}>暫時無法取得模型評估報告。</Text> : null}
        {report.status === 'ok' ? (
          <>
            <Text style={styles.subTitle}>你的訓練歷史（真實資料）</Text>
            <Row label="完成訓練數" value={String(report.data.athlete_history.completed_activities)} />
            <Row label="歷史涵蓋天數" value={String(report.data.athlete_history.history_span_days ?? '—')} />
            {feat?.available ? (
              <>
                <View style={styles.divider} />
                <Text style={styles.subTitle}>用你的資料做預測（模型 vs 你實際做的）</Text>
                <Row label="評估天數" value={String(feat.n_days ?? 0)} />
                <Row
                  label="首選命中率"
                  value={`${Math.round((feat.top_choice_match_rate ?? 0) * 100)}%`}
                />
                {(feat.days ?? []).slice(-6).map((d) => (
                  <View key={d.day_index} style={styles.candRow}>
                    <Text style={styles.candName}>
                      第 {d.day_index} 天 · 預測 {TYPE_LABEL[d.predicted] ?? d.predicted}
                    </Text>
                    <Text style={[styles.candScore, { color: d.matched ? '#047857' : '#b45309' }]}>
                      {d.matched ? '命中' : `實際 ${TYPE_LABEL[d.actual] ?? d.actual}`}
                    </Text>
                  </View>
                ))}
                <Text style={styles.hint}>{feat.note}</Text>
              </>
            ) : null}
            <View style={styles.divider} />
            <Text style={styles.subTitle}>基準模型（邏輯迴歸）指標</Text>
            <Row label="ECE 校準誤差（越低越好）" value={String((agg?.ece ?? 0).toFixed(3))} />
            <Row label="Brier（越低越好）" value={String((agg?.brier ?? 0).toFixed(3))} />
            <Row label="MRR（越高越好）" value={String((agg?.mrr ?? 0).toFixed(3))} />
            <Row label="Top-choice 效用" value={String((agg?.top_choice_utility ?? 0).toFixed(3))} />
            <Row label="是否採用學習模型" value="否 — 生產環境維持規則式" />
            <Text style={styles.hint}>{report.data.note}</Text>
          </>
        ) : null}
      </View>

      {/* 3. Training-load algorithm */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>體能負荷演算法（ACWR）</Text>
        <Text style={styles.formula}>
          {'acute  = Σ session_load（近 7 天）\nchronic = Σ session_load（近 28 天）÷ 4\nratio   = acute ÷ chronic'}
        </Text>
        <Text style={styles.hint}>
          28 天內少於門檻天數有紀錄時，不顯示負荷比，資料品質標記為「不足」，並改給保守的輕鬆課表。這是多個輸入之一，不是單一風險燈號。
        </Text>
      </View>

      {/* 4. Weather-equivalent pace */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>天候等效配速（El Helou 曲線）</Text>
        <Text style={styles.hint}>
          以 El Helou 等人 (2012) 溫度—速度曲線為基礎，改用競賽型（P1）分層，以固定傍晚參考時刻的氣候常態溫度為基準相減，超出實測範圍時用邊界切線外插。詳見專案
          CONTEXT.md。氣溫也是課表排序器的輸入之一（偏熱時降低較高強度的權重）。
        </Text>
      </View>

      {/* 5. Safety-triage rules */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>安全分流規則（固定規則，LLM 不得調整）</Text>
        <Text style={styles.hint}>
          身體回報送出後，先跑固定規則決定緊急度與是否可跑步，之後才附上有來源的衛教資訊。LLM 只能依附給定的實證，不能降低緊急度或放行跑步。
        </Text>
        <View style={styles.divider} />
        <Text style={styles.triageRow}>
          <Text style={styles.tEmergency}>EMERGENCY</Text> — 胸痛／呼吸困難、意識混亂、運動中倒下、嚴重熱傷害 → 不可跑步
        </Text>
        <Text style={styles.triageRow}>
          <Text style={styles.tPrompt}>PROMPT_CLINICIAN</Text> — 嚴重程度分級、明顯外傷、局部骨頭壓痛且負重更痛 → 不可跑步
        </Text>
        <Text style={styles.triageRow}>
          <Text style={styles.tSelf}>SELF_CARE_NEXT_STEP</Text> — 輕度／中度不適，無上述警訊 → 可，但降低強度
        </Text>
      </View>

      {/* 6. Evidence library */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>實證資料庫</Text>
        <Text style={styles.hint}>
          後端維護一份審核過的運動醫學短文圖譜（sports-medicine-v1），涵蓋小腿、膝、阿基里斯腱、足底、脛前、下背、髖／臀等常見部位，含中英雙語關鍵字與來源連結（AAOS
          OrthoInfo、ACSM 等）。傷害回報時以部位檢索，找不到對應時退回一般負荷管理短文，因此引用來源永遠不會是空的。
        </Text>
      </View>

      {/* 7. Version registry */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>版本註冊表</Text>
        <Row label="課表排序器" value={plan.status === 'ok' ? plan.data.ranker_version : 'deterministic-plan-ranker-v2'} />
        <Row label="體能負荷演算法" value="load-2026.08.2" />
        <Row label="課表建議規則" value="guidance-rule-2026.08.1" />
        <Row label="安全分流規則" value="safety-triage-v1" />
        <Row label="實證語料版本" value="sports-medicine-v1" />
        <Text style={styles.hint}>每個後端回應都帶有 algorithm_version，任一數字都能追溯到產生它的規則版本。</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f1f5f9' },
  content: { padding: 16, gap: 14 },
  intro: { fontSize: 12.5, color: '#475569', lineHeight: 19 },
  card: { backgroundColor: '#fff', borderRadius: 14, padding: 16, gap: 8, borderWidth: 1, borderColor: '#e2e8f0' },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#0f172a' },
  subTitle: { fontSize: 13, fontWeight: '700', color: '#334155', marginTop: 2 },
  hint: { fontSize: 12, color: '#64748b', lineHeight: 18 },
  err: { fontSize: 13, color: '#b45309' },
  divider: { height: 1, backgroundColor: '#f1f5f9', marginVertical: 4 },
  kv: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3 },
  kvKey: { fontSize: 12.5, color: '#64748b', flexShrink: 1, paddingRight: 8 },
  kvVal: { fontSize: 12.5, color: '#0f172a', fontWeight: '600' },
  candRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 3 },
  candName: { fontSize: 12.5, color: '#1e293b', flexShrink: 1, paddingRight: 8 },
  candScore: { fontSize: 12.5, color: '#64748b', fontWeight: '600' },
  formula: {
    fontFamily: 'monospace' as any,
    fontSize: 11.5,
    color: '#1e293b',
    backgroundColor: '#f8fafc',
    borderWidth: 1,
    borderColor: '#e2e8f0',
    borderRadius: 8,
    padding: 10,
    lineHeight: 18,
  },
  triageRow: { fontSize: 12, color: '#475569', lineHeight: 19 },
  tEmergency: { fontWeight: '800', color: '#b91c1c' },
  tPrompt: { fontWeight: '800', color: '#b45309' },
  tSelf: { fontWeight: '800', color: '#047857' },
});
