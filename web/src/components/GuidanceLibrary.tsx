import { useEffect, useState } from "react";
import { Article, ArrowSquareOut, Flag, ShieldCheck, TrendUp } from "@phosphor-icons/react";
import { browseGuidanceLibrary } from "../data/apiClient.ts";
import type { GuidancePassageWire } from "../data/apiClient.ts";
import { useAuth } from "../state/AuthContext.tsx";

/** The reviewed guidance behind what the coach says.
 *
 *  Browsable without having reported anything, and organised by recovery
 *  stage: what to do now, what comes next, and what would tell the Athlete
 *  they are ready to move on.
 */

const AREAS: Array<{ value: string; zh: string; en: string }> = [
  { value: "", zh: "全部", en: "All" },
  { value: "膝蓋", zh: "膝蓋", en: "Knee" },
  { value: "阿基里斯腱", zh: "阿基里斯腱", en: "Achilles" },
  { value: "足底筋膜", zh: "足底筋膜", en: "Plantar" },
  { value: "小腿脛骨", zh: "小腿脛骨", en: "Shin" },
  { value: "小腿", zh: "小腿", en: "Calf" },
  { value: "大腿後側", zh: "大腿後側", en: "Hamstring" },
  { value: "髖關節", zh: "髖關節", en: "Hip" },
];

const STAGES: Array<{
  value: string;
  zh: string;
  en: string;
  icon: typeof ShieldCheck;
}> = [
  { value: "", zh: "全部階段", en: "All stages", icon: Article },
  { value: "PROTECTION", zh: "保護期", en: "Protect", icon: ShieldCheck },
  { value: "LOADING", zh: "漸進加載", en: "Load", icon: TrendUp },
  { value: "RETURN_TO_RUN", zh: "回場跑", en: "Return to run", icon: Flag },
];

export function GuidanceLibrary({
  en,
  initialBodyPart,
  initialPhase,
}: {
  en: boolean;
  initialBodyPart?: string;
  initialPhase?: string;
}) {
  const { auth } = useAuth();
  const [bodyPart, setBodyPart] = useState(initialBodyPart ?? "");
  const [phase, setPhase] = useState(initialPhase ?? "");
  const [passages, setPassages] = useState<GuidancePassageWire[] | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  useEffect(() => {
    if (!auth?.accessToken) return;
    let cancelled = false;
    setStatus("loading");

    browseGuidanceLibrary(auth.accessToken, {
      bodyPart: bodyPart || undefined,
      phase: phase || undefined,
    })
      .then((response) => {
        if (cancelled) return;
        setPassages(response.passages);
        setStatus("idle");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [auth?.accessToken, bodyPart, phase]);

  return (
    <div className="gl">
      <p className="gl-intro">
        {en
          ? "Everything your coach says is anchored to published sports medicine and exercise science guidance. Browse it here, whether or not anything hurts."
          : "教練說的每一句話，都對齊已發表的運動醫學與運動科學指引。這裡隨時可以翻閱，不必等到哪裡不舒服。"}
      </p>

      <FilterRow
        label={en ? "Area" : "部位"}
        options={AREAS.map((area) => ({
          value: area.value,
          label: en ? area.en : area.zh,
        }))}
        selected={bodyPart}
        onSelect={setBodyPart}
      />
      <FilterRow
        label={en ? "Stage" : "階段"}
        options={STAGES.map((stage) => ({
          value: stage.value,
          label: en ? stage.en : stage.zh,
        }))}
        selected={phase}
        onSelect={setPhase}
      />

      {status === "loading" && !passages && (
        <p className="gl-note">{en ? "Loading guidance…" : "正在載入指引…"}</p>
      )}

      {status === "error" && (
        <p className="gl-note gl-note--error" role="alert">
          {en ? "Could not load the guidance just now." : "目前無法載入指引，稍後再試。"}
        </p>
      )}

      {passages?.length === 0 && status === "idle" && (
        <p className="gl-note">
          {en ? "Nothing matches those filters yet." : "這個篩選條件目前沒有對應的內容。"}
        </p>
      )}

      {passages && passages.length > 0 && (
        <ul className="gl-list">
          {passages.map((passage) => (
            <GuidanceCard key={passage.evidence_id} passage={passage} en={en} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterRow({
  label,
  options,
  selected,
  onSelect,
}: {
  label: string;
  options: Array<{ value: string; label: string }>;
  selected: string;
  onSelect: (value: string) => void;
}) {
  return (
    <div className="gl-filter" role="group" aria-label={label}>
      <span className="gl-filter-label">{label}</span>
      <div className="gl-filter-options">
        {options.map((option) => (
          <button
            key={option.value || "all"}
            type="button"
            className="cc-choice cc-choice--sm"
            aria-pressed={option.value === selected}
            onClick={() => onSelect(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function GuidanceCard({ passage, en }: { passage: GuidancePassageWire; en: boolean }) {
  const stage = STAGES.find((entry) => entry.value === passage.phase);
  const StageIcon = stage?.icon ?? Article;

  return (
    <li className="gl-item">
      <h3 className="gl-title">
        <StageIcon size={16} weight="bold" aria-hidden="true" className="gl-title-icon" />
        <span>{passage.title}</span>
      </h3>

      <div className="gl-meta">
        <span>{passage.publisher}</span>
        <a href={passage.source_url} target="_blank" rel="noopener noreferrer" className="gl-source">
          {en ? "Open source" : "查看原文"}
          <ArrowSquareOut size={12} aria-hidden="true" />
        </a>
      </div>

      <p className="gl-text">{passage.text}</p>

      {passage.phase_purpose && (
        <div className="gl-stage">
          <p>
            <strong>{en ? "What this stage is for: " : "這個階段的目的："}</strong>
            {passage.phase_purpose}
          </p>
          {passage.progression_criterion && (
            <p>
              <strong>{en ? "Ready for the next stage when: " : "可以進到下一階段的條件："}</strong>
              {passage.progression_criterion}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
