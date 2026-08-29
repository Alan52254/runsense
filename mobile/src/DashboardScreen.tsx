import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSession } from './SessionContext';
import {
  getInjuryReports,
  getTodayGuidance,
  getTrainingLoadTrend,
  getTrainingPlanToday,
  getWeather,
  InjuryReportResponse,
  TodayGuidanceResponse,
  TrainingLoadPoint,
  TrainingPlanResponse,
  WeatherResponse,
} from './api';
import { buildRecommendationView, RECOMMENDATION_DISCLAIMER } from './recommendation';
import { formatLoad, formatRatio, formatTemperature } from './format';

type Section<T> = { status: 'loading' } | { status: 'ok'; data: T } | { status: 'error' };

const L = 'zh-TW' as const;

export default function DashboardScreen({ navigation }: { navigation: any }) {
  const { request, logout } = useSession();
  const insets = useSafeAreaInsets();
  const [refreshing, setRefreshing] = useState(false);
  const [guidance, setGuidance] = useState<Section<TodayGuidanceResponse>>({ status: 'loading' });
  const [weather, setWeather] = useState<Section<WeatherResponse>>({ status: 'loading' });
  const [trend, setTrend] = useState<Section<TrainingLoadPoint | null>>({ status: 'loading' });
  const [body, setBody] = useState<Section<InjuryReportResponse | null>>({ status: 'loading' });
  const [plan, setPlan] = useState<Section<TrainingPlanResponse>>({ status: 'loading' });

  const load = useCallback(async () => {
    const settle = <T,>(r: PromiseSettledResult<T>, set: (s: Section<T>) => void) => {
      if (r.status === 'fulfilled') set({ status: 'ok', data: r.value });
      else set({ status: 'error' });
    };
    const [g, w, t, b, p] = await Promise.allSettled([
      request((tok) => getTodayGuidance(tok)),
      request((tok) => getWeather(tok)),
      request((tok) => getTrainingLoadTrend(tok)),
      request((tok) => getInjuryReports(tok)),
      request((tok) => getTrainingPlanToday(tok)),
    ]);
    settle(g, setGuidance);
    settle(w, setWeather);
    if (t.status === 'fulfilled') {
      const series = t.value.series[0];
      setTrend({ status: 'ok', data: series ? series.points[series.points.length - 1] ?? null : null });
    } else setTrend({ status: 'error' });
    if (b.status === 'fulfilled') {
      setBody({ status: 'ok', data: b.value.items[0] ?? null });
    } else setBody({ status: 'error' });
    settle(p, setPlan);
    setRefreshing(false);
  }, [request]);

  useEffect(() => {
    load();
  }, [load]);

  const view =
    guidance.status === 'ok'
      ? buildRecommendationView(guidance.data, weather.status === 'ok' ? weather.data : null)
      : null;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 28 }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            load();
          }}
        />
      }
    >
      <View style={styles.header}>
        <View>
          <Text style={styles.greeting}>今日訓練基地</Text>
          <Text style={styles.date}>
            {view?.localDate ?? new Date().toISOString().slice(0, 10)}
          </Text>
        </View>
        <TouchableOpacity style={styles.logout} onPress={logout}>
          <Text style={styles.logoutText}>登出</Text>
        </TouchableOpacity>
      </View>

      {/* --- Today's recommendation --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>今日課表</Text>
        {guidance.status === 'loading' ? <ActivityIndicator /> : null}
        {guidance.status === 'error' ? (
          <View>
            <Text style={styles.errText}>無法載入今日課表。請確認網路連線後重試。</Text>
            <TouchableOpacity style={styles.retry} onPress={load}>
              <Text style={styles.retryText}>重試</Text>
            </TouchableOpacity>
          </View>
        ) : null}
        {view ? (
          <>
            <Text style={styles.workoutType}>{view.workoutType}</Text>
            <Text style={styles.intensity}>強度 {view.intensityLabel}</Text>
            <View style={styles.tileRow}>
              <Tile label="預計時長" value={view.durationLabel} />
              <Tile label="預計距離" value={view.distanceLabel} />
            </View>
            <View style={styles.tileRow}>
              <Tile label="目標配速" value={view.targetPaceLabel} />
              <Tile
                label="天候等效配速"
                value={view.weatherAdjustedPaceLabel ?? '暫無資料'}
              />
            </View>

            <View style={styles.toneBox}>
              <Text style={styles.toneLabel}>教練語氣提示</Text>
              <Text style={styles.toneText}>{view.toneText}</Text>
              <Text style={styles.toneAttribution}>
                由真人審核字句挑選（{view.toneReviewedBy || '未標示'}），非 AI 撰寫
              </Text>
            </View>

            <Text style={styles.disclaimer}>{RECOMMENDATION_DISCLAIMER[L]}</Text>
            <Text style={styles.algoLine}>規則引擎版本 {view.algorithmVersion}</Text>
          </>
        ) : null}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>智慧課表決策</Text>
        {plan.status === 'loading' ? <ActivityIndicator /> : null}
        {plan.status === 'error' ? <Text style={styles.errText}>暫時無法載入課表決策。</Text> : null}
        {plan.status === 'ok' ? (
          <>
            <Text style={styles.workoutType}>{plan.data.candidates[0]?.workout_type ?? '無候選課表'}</Text>
            <Text style={styles.bodyLine}>
              {plan.data.candidates[0]?.running_allowed ? '允許進行保守訓練' : '今天不建議跑步，請尋求專業評估'}
            </Text>
            {plan.data.abstained ? (
              <Text style={styles.errText}>資料不足，系統已保守 abstain（{plan.data.abstention_reason}）。</Text>
            ) : null}
            <Text style={styles.algoLine}>
              特徵涵蓋：負荷 {plan.data.feature_coverage.training_load ? '有' : '無'}／天氣 {plan.data.feature_coverage.weather ? '有' : '無'}／傷勢 {plan.data.feature_coverage.injury_triage ? '有' : '無'}
            </Text>
            <Text style={styles.disclaimer}>課表為輔助決策，不是醫療診斷；疼痛加劇或有警訊時請停止運動並就醫。</Text>
          </>
        ) : null}
      </View>

      {/* --- Weather --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>天候狀況與配速補償</Text>
        {weather.status === 'loading' ? <ActivityIndicator /> : null}
        {weather.status === 'error' || (weather.status === 'ok' && weather.data.state === 'UNAVAILABLE') ? (
          <Text style={styles.errText}>目前無法取得即時天氣資料。</Text>
        ) : null}
        {weather.status === 'ok' && weather.data.state !== 'UNAVAILABLE' ? (
          <>
            <Text style={styles.weatherState}>狀態：{weather.data.state}</Text>
            <View style={styles.tileRow}>
              <Tile label="氣溫" value={formatTemperature(weather.data.temperature_c)} />
              <Tile
                label="相對濕度"
                value={weather.data.humidity_pct != null ? `${weather.data.humidity_pct}%` : '--'}
              />
            </View>
            <Text style={styles.weatherFoot}>
              氣候配速影響：
              {weather.data.pace_adjustment_sec_per_km != null
                ? `${weather.data.pace_adjustment_sec_per_km > 0 ? '+' : ''}${weather.data.pace_adjustment_sec_per_km}s / km`
                : '暫無資料'}
            </Text>
          </>
        ) : null}
      </View>

      {/* --- Training load (neutral text only, REQ-METRIC-001) --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>體能與疲勞指標</Text>
        {trend.status === 'loading' ? <ActivityIndicator /> : null}
        {trend.status === 'error' ? (
          <Text style={styles.errText}>暫時無法載入負荷資料。</Text>
        ) : null}
        {trend.status === 'ok' ? (
          <View style={styles.tileRow2}>
            <Tile label="近 7 天負荷" value={formatLoad(trend.data?.acute_load)} />
            <Tile label="28 天基準" value={formatLoad(trend.data?.chronic_load)} />
            <Tile label="短長期負荷比" value={formatRatio(trend.data?.load_ratio ?? null)} />
            <Tile
              label="有效觀測天數"
              value={trend.data?.observation_days != null ? String(trend.data.observation_days) : '--'}
            />
          </View>
        ) : null}
        {trend.status === 'ok' && trend.data ? (
          <Text style={styles.algoLine}>資料品質：{trend.data.data_quality}</Text>
        ) : null}
      </View>

      {/* --- Body snapshot --- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>身體與疲勞狀況</Text>
        {body.status === 'loading' ? <ActivityIndicator /> : null}
        {body.status === 'error' ? (
          <Text style={styles.errText}>暫時無法載入身體狀況紀錄。</Text>
        ) : null}
        {body.status === 'ok' && body.data ? (
          <Text style={styles.bodyLine}>
            {body.data.local_training_date} ·{' '}
            {body.data.has_issue
              ? `${body.data.body_part ?? '未指定部位'}（${body.data.severity_band}）`
              : '回報無不適'}
          </Text>
        ) : null}
        {body.status === 'ok' && !body.data ? (
          <Text style={styles.bodyLine}>尚無回報紀錄。</Text>
        ) : null}
        <TouchableOpacity style={styles.retry} onPress={() => navigation.navigate('Body')}>
          <Text style={styles.retryText}>前往回報身體狀況</Text>
        </TouchableOpacity>
      </View>

      {/* --- Quick actions --- */}
      <View style={styles.actions}>
        <TouchableOpacity
          style={[styles.action, styles.actionPrimary]}
          onPress={() => navigation.navigate('LiveRun')}
        >
          <Text style={styles.actionPrimaryText}>出發開跑！</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.action, styles.actionSecondary]}
          onPress={() => navigation.navigate('LogWorkout')}
        >
          <Text style={styles.actionSecondaryText}>手動補登</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.tile}>
      <Text style={styles.tileLabel}>{label}</Text>
      <Text style={styles.tileValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f1f5f9' },
  content: { padding: 16, gap: 14 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  greeting: { fontSize: 22, fontWeight: '800', color: '#0f172a' },
  date: { fontSize: 13, color: '#64748b', marginTop: 2 },
  logout: { paddingVertical: 6, paddingHorizontal: 12, borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 8, backgroundColor: '#fff' },
  logoutText: { fontSize: 13, color: '#475569', fontWeight: '600' },
  card: { backgroundColor: '#fff', borderRadius: 14, padding: 16, gap: 8, borderWidth: 1, borderColor: '#e2e8f0' },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#0f172a' },
  workoutType: { fontSize: 18, fontWeight: '800', color: '#0f172a', marginTop: 2 },
  intensity: { fontSize: 12, color: '#64748b', textTransform: 'uppercase' },
  tileRow: { flexDirection: 'row', gap: 8 },
  tileRow2: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tile: { flex: 1, minWidth: '45%', backgroundColor: '#f8fafc', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: '#e2e8f0' },
  tileLabel: { fontSize: 11, color: '#64748b', fontWeight: '600', marginBottom: 3 },
  tileValue: { fontSize: 17, fontWeight: '800', color: '#0f172a' },
  toneBox: { backgroundColor: '#f8fafc', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: '#e2e8f0', marginTop: 4 },
  toneLabel: { fontSize: 11, fontWeight: '700', color: '#475569' },
  toneText: { fontSize: 13, color: '#1e293b', marginTop: 3, lineHeight: 18 },
  toneAttribution: { fontSize: 11, color: '#94a3b8', marginTop: 4 },
  disclaimer: { fontSize: 11, color: '#64748b', lineHeight: 16, marginTop: 6 },
  algoLine: { fontSize: 10, color: '#94a3b8', marginTop: 4 },
  weatherState: { fontSize: 12, color: '#64748b' },
  weatherFoot: { fontSize: 12, color: '#475569', marginTop: 4 },
  bodyLine: { fontSize: 13, color: '#1e293b' },
  errText: { fontSize: 13, color: '#b45309', lineHeight: 18 },
  retry: { alignSelf: 'flex-start', marginTop: 8, paddingVertical: 6, paddingHorizontal: 12, backgroundColor: '#f1f5f9', borderRadius: 8, borderWidth: 1, borderColor: '#cbd5e1' },
  retryText: { fontSize: 12, fontWeight: '600', color: '#334155' },
  actions: { flexDirection: 'row', gap: 10, marginTop: 2 },
  action: { flex: 1, paddingVertical: 14, borderRadius: 12, alignItems: 'center' },
  actionPrimary: { backgroundColor: '#ea580c' },
  actionPrimaryText: { color: '#fff', fontWeight: '800', fontSize: 15 },
  actionSecondary: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#cbd5e1' },
  actionSecondaryText: { color: '#0f172a', fontWeight: '700', fontSize: 15 },
});
