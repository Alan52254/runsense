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
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
        {en
          ? "Everything your coach says is anchored to published sports medicine and exercise science guidance. Browse it here, whether or not anything hurts."
          : "教練說的每一句話，都對齊已發表的運動醫學與運動科學指引。這裡隨時可以翻閱，不必等到哪裡不舒服。"}
      </div>

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
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {en ? "Loading guidance…" : "正在載入指引…"}
        </div>
      )}

      {status === "error" && (
        <div style={{ fontSize: 13, color: "var(--critical)" }}>
          {en
            ? "Could not load the guidance just now."
            : "目前無法載入指引，稍後再試。"}
        </div>
      )}

      {passages?.length === 0 && status === "idle" && (
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {en
            ? "Nothing matches those filters yet."
            : "這個篩選條件目前沒有對應的內容。"}
        </div>
      )}

      {passages?.map((passage) => (
        <GuidanceCard key={passage.evidence_id} passage={passage} en={en} />
      ))}
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
    <div>
      <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 5 }}>{label}</div>
      <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 2 }}>
        {options.map((option) => {
          const active = option.value === selected;
          return (
            <button
              key={option.value || "all"}
              onClick={() => onSelect(option.value)}
              style={{
                whiteSpace: "nowrap",
                padding: "5px 11px",
                borderRadius: 14,
                border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
                backgroundColor: active ? "var(--accent-soft)" : "var(--surface-sunken)",
                color: active ? "var(--accent-ink)" : "var(--text-2)",
                fontWeight: active ? 750 : 550,
                fontSize: 11.5,
                cursor: "pointer",
              }}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function GuidanceCard({ passage, en }: { passage: GuidancePassageWire; en: boolean }) {
  const stage = STAGES.find((entry) => entry.value === passage.phase);
  const StageIcon = stage?.icon ?? Article;

  return (
    <div
      style={{
        backgroundColor: "var(--surface-sunken)",
        padding: 14,
        borderRadius: 12,
        border: "1px solid var(--border)",
      }}
    >
      <div
        style={{
          fontWeight: 800,
          fontSize: 13.5,
          color: "var(--accent-ink)",
          marginBottom: 4,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <StageIcon size={16} weight="bold" aria-hidden="true" />
        <span>{passage.title}</span>
      </div>

      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          marginBottom: 8,
          display: "flex",
          alignItems: "center",
          gap: 6,
          flexWrap: "wrap",
        }}
      >
        <span>{passage.publisher}</span>
        <a
          href={passage.source_url}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
            color: "var(--accent)",
            textDecoration: "none",
          }}
        >
          {en ? "Open source" : "查看原文"}
          <ArrowSquareOut size={12} aria-hidden="true" />
        </a>
      </div>

      <div style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--text-2)" }}>
        {passage.text}
      </div>

      {passage.phase_purpose && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "1px dashed var(--border)",
            fontSize: 12,
            lineHeight: 1.6,
            color: "var(--text-2)",
          }}
        >
          <div>
            <strong>{en ? "What this stage is for: " : "這個階段的目的："}</strong>
            {passage.phase_purpose}
          </div>
          {passage.progression_criterion && (
            <div style={{ marginTop: 4 }}>
              <strong>{en ? "Ready for the next stage when: " : "可以進到下一階段的條件："}</strong>
              {passage.progression_criterion}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
