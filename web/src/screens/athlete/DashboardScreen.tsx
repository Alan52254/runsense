import { useMemo, useState } from "react";
import { Badge, Button, Notice } from "../../components/ui.tsx";
import type { TickerItem } from "../../components/motion.tsx";
import { useShellTicker } from "../../app/shellTicker.tsx";
import type { ShellTickerContribution } from "../../app/shellTicker.tsx";
import "../../styles/athlete.css";
import { resolveDisplayedTrainingLoad } from "../../lib/trainingLoadDisplay.ts";
import { deriveTodayViewModel } from "../../lib/todayViewModel.ts";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import { useLocale } from "../../state/LocaleContext.tsx";
import { formatLocalDateLong } from "../../lib/format.ts";
import { DASHBOARD_COPY, climateShiftLabel, interpolate } from "./today/todayCopy.ts";
import { TodayHero } from "./today/TodayHero.tsx";
import { acwrChipText } from "../../lib/acwr.ts";
import { CoachSessionStructure, SystemSessionStructure } from "./today/SessionStructure.tsx";
import { RankedPlanPanel } from "./today/RankedPlanPanel.tsx";
import { UpcomingAssignments } from "./today/UpcomingAssignments.tsx";
import {
  BodyStatusPanel,
  CoachInsightPanel,
  RecentActivitiesPanel,
  SlotsPanel,
  bodyStatusLabel,
} from "./today/TodaySidePanels.tsx";
import { ConditionsDrawer, LoadDrawer } from "./today/TodayDrawers.tsx";
import { Row, Stack } from "../../components/Layout.tsx";

export function DashboardScreen() {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const en = locale === "en";
  const c = DASHBOARD_COPY[locale];
  const {
    today,
    trainingLoad,
    allActivities,
    injuryReports,
    weather,
    recommendation,
    toneVariants,
    selectedToneVariantId,
    preferences,
    setPreference,
    liveWeather,
    weatherStatus,
    liveGuidance,
    guidanceStatus,
    refetchGuidance,
    liveTrainingPlan,
    myAssignedWorkouts,
  } = useWorkspace();

  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [envOpen, setEnvOpen] = useState(false);
  const [loadOpen, setLoadOpen] = useState(false);

  const displayedLoad = useMemo(
    () => resolveDisplayedTrainingLoad(allActivities, trainingLoad, today),
    [allActivities, trainingLoad, today],
  );
  const loadRatio = displayedLoad.trainingLoad.units[0]?.loadRatio ?? null;

  const vm = useMemo(
    () =>
      deriveTodayViewModel(
        {
          locale,
          apiConfigured,
          plan: liveTrainingPlan,
          selectedCandidateId,
          guidance: liveGuidance,
          offlineRecommendation: recommendation,
          liveWeather,
          offlineWeather: weather,
          loadRatio,
        },
        new Date(),
      ),
    [locale, liveTrainingPlan, selectedCandidateId, liveGuidance, recommendation, liveWeather, weather, loadRatio],
  );

  const todayHasRecord = allActivities.some((a) => a.localTrainingDate === today);
  const latestInjury = injuryReports[0];
  const redFlag = latestInjury?.hasIssue === true && latestInjury.severityBand === "SEVERE";

  // A coach's plan for today takes the hero; later ones get their own list.
  const todaysAssignments = myAssignedWorkouts.filter((w) => w.localDate === today);
  const upcomingAssignedWorkouts = myAssignedWorkouts
    .filter((w) => w.localDate > today)
    .sort((a, b) => a.localDate.localeCompare(b.localDate));
  // Coach paces are assumed calibrated for a typical early evening, so they
  // move by the loss relative to that (see weather_pace.py).
  const coachPaceLossPct = vm.weather.speedLossPctRelativeToNormal ?? 0;
  const coachSource = preferences.trainingSource === "coach";

  const fallbackTone = toneVariants.find((t) => t.id === "NEUTRAL_FALLBACK")!;
  const selectedTone = toneVariants.find((t) => t.id === selectedToneVariantId) ?? toneVariants[0];
  const toneText =
    apiConfigured && liveGuidance ? liveGuidance.tone_text : (preferences.llmToneEnabled ? selectedTone : fallbackTone).text;
  // The neutral fallback line only restates that a plan exists; say why
  // today's plan was chosen instead, or nothing.
  const toneIsFiller =
    !toneText.trim() || toneText === fallbackTone.text || liveGuidance?.tone_variant_id === "NEUTRAL_FALLBACK";
  const insightText = toneIsFiller ? vm.rankingReason : toneText;

  const { temperatureC, humidityPct, city, state: weatherState } = vm.weather;
  const { speedLossPct } = vm.climate;
  const { ratio: acwr, zone: acwrZone } = vm.acwr;
  const bodyLabel = bodyStatusLabel(latestInjury, locale);
  const tickerContribution = useMemo<ShellTickerContribution>(() => {
    const items: TickerItem[] = [];
    if (weatherState !== "UNAVAILABLE" && temperatureC !== null && temperatureC !== undefined) {
      items.push({
        id: "weather",
        icon: "thermometer",
        tone: "climate",
        text: en
          ? `${city} ${temperatureC.toFixed(0)}°C · ${humidityPct ?? "—"}% humidity`
          : `${city} ${temperatureC.toFixed(0)}°C · 濕度 ${humidityPct ?? "—"}%`,
      });
      items.push({ id: "pace-impact", icon: "wind", tone: "climate", text: climateShiftLabel(speedLossPct, null, c, locale) });
    } else {
      items.push({ id: "weather", icon: "cloud", tone: "neutral", text: c.weatherUnavailable });
    }
    items.push({
      id: "acwr",
      icon: "gauge",
      tone: acwrZone === "safe" ? "safe" : acwrZone === null || acwrZone === "low" ? "neutral" : acwrZone === "high" ? "brand" : "alert",
      text: acwrChipText(acwr, locale),
    });
    items.push({ id: "triage", icon: redFlag ? "alert" : "shield", tone: redFlag ? "alert" : "neutral", text: bodyLabel });
    return {
      items,
      onOpenDetails: () => setEnvOpen(true),
      detailsLabel: en ? "Weather and conditions" : "天候與環境詳情",
    };
  }, [en, c, locale, city, temperatureC, humidityPct, weatherState, speedLossPct, acwr, acwrZone, redFlag, bodyLabel]);
  useShellTicker(tickerContribution);

  return (
    <div className="dashboard-container ath-dash">
      <div className="page-head ath-head">
        <Stack gap={1}>
          <Row gap={2}>
            <h1 className="page-title">{auth?.athlete.name}</h1>
            <Badge tone="good" dot>{auth?.athlete.city || "Taipei"}</Badge>
          </Row>
          <p className="page-desc">
            {formatLocalDateLong(today, locale)} · {interpolate(c.timezone, { timezone: auth?.athlete.timezone ?? "Asia/Taipei" })}
          </p>
        </Stack>
      </div>

      {apiConfigured && guidanceStatus === "loading" && !liveGuidance && (
        <Notice tone="neutral" icon="info">{c.loadingPlan}</Notice>
      )}
      {apiConfigured && guidanceStatus === "error" && (
        <Notice tone="critical" icon="alert" title={c.planError}>
          <Row justify="between" gap={3}>
            <span>{c.planErrorBody}</span>
            <Button size="sm" onClick={() => void refetchGuidance()}>{c.retry}</Button>
          </Row>
        </Notice>
      )}

      <div className="ath-dash-grid">
        <div className="ath-main">
          {/* Layer 1: the three-second departure decision */}
          <TodayHero
            vm={vm}
            c={c}
            locale={locale}
            trainingSource={preferences.trainingSource}
            onTrainingSource={(next) => setPreference("trainingSource", next)}
            todaysAssignments={todaysAssignments}
            coachPaceLossPct={coachPaceLossPct}
            todayHasRecord={todayHasRecord}
          />

          {/* Layer 2: the workout structure rail */}
          {coachSource
            ? todaysAssignments.map((assignment) => (
                <CoachSessionStructure
                  key={assignment.id}
                  assignment={assignment}
                  accessToken={auth?.accessToken ?? null}
                  coachPaceLossPct={coachPaceLossPct}
                  slots={vm.weather.timeOfDayEstimates}
                  c={c}
                  locale={locale}
                />
              ))
            : !vm.isRestDay && (
                <SystemSessionStructure segments={vm.workout.segments} speedLossPct={speedLossPct} locale={locale} />
              )}

          {/* below the fold: the ranked recommendation */}
          {!coachSource && (
            <RankedPlanPanel
              vm={vm}
              confidence={liveTrainingPlan?.confidence ?? null}
              observationDays={liveTrainingPlan?.inputs?.observation_days ?? null}
              locale={locale}
              onSelect={setSelectedCandidateId}
            />
          )}

          <UpcomingAssignments workouts={upcomingAssignedWorkouts} c={c} locale={locale} />
        </div>

        <aside className="ath-side">
          <SlotsPanel slots={vm.climate.slots} active={vm.climate.activeSlot} c={c} locale={locale} />
          <BodyStatusPanel latest={latestInjury} c={c} locale={locale} />
          <CoachInsightPanel text={insightText} isRestDay={vm.isRestDay} c={c} locale={locale} onOpenLoad={() => setLoadOpen(true)} />
          <RecentActivitiesPanel activities={allActivities.slice(0, 4)} c={c} locale={locale} />
        </aside>
      </div>

      {/* Layer 3: drawers */}
      <LoadDrawer
        open={loadOpen}
        onClose={() => setLoadOpen(false)}
        displayedLoad={displayedLoad}
        activities={allActivities}
        today={today}
        c={c}
        locale={locale}
      />
      <ConditionsDrawer
        open={envOpen}
        onClose={() => setEnvOpen(false)}
        vm={vm}
        loading={apiConfigured && weatherStatus === "loading" && !liveWeather}
        c={c}
        locale={locale}
      />
    </div>
  );
}
