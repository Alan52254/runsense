import { Surface } from "../../../components/Surface.tsx";
import { Badge } from "../../../components/ui.tsx";
import type { TodayViewModel } from "../../../lib/todayViewModel.ts";
import { Figure } from "../../../components/Figure.tsx";
import { acwrValueText } from "../../../lib/acwr.ts";

/** 比較其他課表: the ranker's candidates, any of which can be applied to the
 *  hero. Each row has a place (tied scores share one), its own purpose, and
 *  the server's reason only when it differs from the others' -- an identical
 *  reason is said once above the list. 首選 only marks a clear winner. */
export function RankedPlanPanel({ vm, confidence, observationDays, locale, onSelect }: {
  vm: TodayViewModel;
  confidence: number | null;
  observationDays: number | null;
  locale: "zh-TW" | "en";
  onSelect: (candidateId: string) => void;
}) {
  const en = locale === "en";
  const reason = vm.rankingSharedReason ?? vm.rankingReason;
  const ratio = vm.acwr.ratio;

  return (
    <Surface as="details" className="ath-panel ath-disclosure">
      <summary className="ath-disclosure-summary">
        <span>{en ? "Compare other workouts" : "比較其他課表"}</span>
        <span className="ath-disclosure-hint">{en ? "Options and selection reasons" : "備選方案與建議依據"}</span>
      </summary>
      <div className="ath-disclosure-content">
        <div className="ath-rank-head">
          <h2 className="ath-panel-title" id="ath-rank-title">
            {en ? "Today's workouts, ranked" : "今日課表排序"}
          </h2>
          <Badge tone={confidence != null ? "good" : "warning"}>
            {confidence != null
              ? `${en ? "Personalised: " : "個人化程度："}${(confidence * 100).toFixed(0)}%`
              : en ? "Conservative — not enough of your data yet" : "保守建議 — 你的資料還不足以個人化"}
          </Badge>
        </div>
        {reason && <p className="ath-rank-reason">{en ? "Why: " : "依據："}{reason}</p>}

        <ol className="ath-rank-list" aria-labelledby="ath-rank-title">
          {vm.ranking.length === 0 && (
            <li className="ath-panel-sub">{en ? "No alternative workouts available yet." : "目前沒有可比較的備選課表。"}</li>
          )}
          {vm.ranking.map((row, i) => (
            <li key={row.id || i}>
              <button
                type="button"
                className={`ath-rank-row${row.isSelected ? " is-active" : ""}`}
                aria-pressed={row.isSelected}
                onClick={() => onSelect(row.id)}
              >
                <span className="ath-rank-place tnum" aria-label={en ? `Rank ${row.rank}` : `第 ${row.rank} 名`}>
                  {row.rank}
                </span>
                <span className="ath-rank-body">
                  <span className="ath-rank-name">
                    <strong>{row.label}</strong>
                    {row.durationMinutes > 0 && (
                      <span className="ath-rank-meta">
                        {en ? `${row.durationMinutes} min` : `${row.durationMinutes} 分鐘`} · <Figure kind="distance" meters={row.distanceKm * 1000} />
                      </span>
                    )}
                    {row.isTop && <Badge tone="good">{en ? "Top pick" : "首選"}</Badge>}
                    {row.isSelected && <Badge tone="accent" dot>{en ? "In use" : "已套用"}</Badge>}
                  </span>
                  {row.purpose && <span className="ath-rank-why">{row.purpose}</span>}
                  {row.rationale && <span className="ath-rank-why">{row.rationale}</span>}
                </span>
                {row.fit !== null && (
                  <span className="ath-rank-fit">
                    <small>{en ? "Fit" : "適合度"}</small>
                    <span className="tnum">{row.fit}</span>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ol>

        <div className="ath-rank-foot">
          <span>
            {en ? "ACWR: " : "ACWR 負荷比："}
            <strong className="tnum">{acwrValueText(ratio, locale)}</strong>
          </span>
          <span>
            {en ? "Obs Days: " : "觀測天數："}
            <strong className="tnum">{observationDays ?? "—"}</strong>
          </span>
        </div>
      </div>
    </Surface>
  );
}
