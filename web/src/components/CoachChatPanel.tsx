import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { PaperPlaneTilt, WarningCircle, WarningOctagon, X } from "@phosphor-icons/react";
import { MarkdownMessage } from "./MarkdownMessage.tsx";
import { CoachThinking } from "./CoachThinking.tsx";
import { CoachProposalCard } from "./CoachProposalCard.tsx";
import { GuidanceLibrary } from "./GuidanceLibrary.tsx";
import { citationsOf, isBusy, pendingProposal, visibleText } from "../lib/coachConversation.ts";
import type { CoachPhase, ThinkingStep } from "../lib/coachConversation.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import type { CoachTab } from "../state/CoachChatContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";

const BODY_PARTS = [
  "膝蓋 (Knee)",
  "阿基里斯腱 (Achilles)",
  "足底筋膜 (Plantar)",
  "小腿脛骨 (Shin Splints)",
  "大腿後側 (Hamstring)",
  "髖關節 (Hip)",
];

const SEVERITIES = ["輕微 (Mild)", "中度 (Moderate)", "嚴重 (Severe)"];

/** The health-coach conversation: tabs, body and composer. The drawer and the
 *  健康教練 page are frames around this one panel; its state lives in
 *  CoachChatProvider, so both show the same conversation. */
export function CoachChatPanel({
  variant,
  titleId,
  onClose,
}: {
  variant: "drawer" | "page";
  titleId?: string;
  onClose?: () => void;
}) {
  const { locale } = useLocale();
  const { trainingLoad, liveWeather } = useWorkspace();
  const coach = useCoachChat();
  const { phase, messages, activeTab, setActiveTab, reportContext } = coach;
  const en = locale === "en";
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }, [messages, phase, activeTab]);

  // The signed-in Athlete's own figures. Without enough observation they see
  // an em dash, never an invented number.
  const primaryUnit = trainingLoad.units[0] ?? null;
  const unitSuffix = primaryUnit?.unit === "AU" ? "AU" : "";
  const acuteLoad = primaryUnit ? String(Math.round(primaryUnit.acuteLoad)) : "—";
  const chronicLoad = primaryUnit ? String(Math.round(primaryUnit.chronicLoad)) : "—";
  const loadRatio =
    primaryUnit && primaryUnit.loadRatio !== null ? primaryUnit.loadRatio.toFixed(2) : "—";
  const temperatureC =
    liveWeather && liveWeather.state !== "UNAVAILABLE" ? liveWeather.temperature_c : null;
  const speedLossPct = liveWeather?.speed_loss_pct_relative_to_normal ?? null;
  const humidityPct =
    liveWeather?.humidity_pct !== null && liveWeather?.humidity_pct !== undefined
      ? Math.round(liveWeather.humidity_pct)
      : null;

  const quickPrompts = en
    ? [
        loadRatio === "—"
          ? "What should I run today given my recent records?"
          : `My current load ratio is ${loadRatio}. What should I pay attention to today?`,
        temperatureC !== null && humidityPct !== null
          ? `It is ${Math.round(temperatureC)}°C and ${humidityPct}% humidity — how should I adjust my pace?`
          : "How should I adjust my pace for the current weather?",
        "I only have 30 minutes today.",
        reportContext
          ? `My latest report is ${reportContext.bodyPart} (${reportContext.severityBand}). What should I do next?`
          : "Does my latest body report mean I should adjust today's training?",
      ]
    : [
        loadRatio === "—"
          ? "依我近期紀錄，今天訓練要注意什麼？"
          : `我目前負荷比是 ${loadRatio}，今天訓練要注意什麼？`,
        temperatureC !== null && humidityPct !== null
          ? `今天 ${Math.round(temperatureC)}°C、濕度 ${humidityPct}%，配速要怎麼調整？`
          : "依當前天候，配速要怎麼調整？",
        "我今天只有 30 分鐘。",
        reportContext
          ? `我最近回報 ${reportContext.bodyPart}（${reportContext.severityBand}），下一步該怎麼做？`
          : "依最近一次身體回報，今天需要調整訓練嗎？",
      ];

  const tabs: { id: CoachTab; label: string }[] = [
    { id: "chat", label: en ? "Ask" : "問教練" },
    { id: "injury", label: en ? "How you feel" : "身體回報" },
    { id: "guidance", label: en ? "Guidance" : "專業指引" },
  ];
  const tabId = (tab: CoachTab) => `cc-${variant}-tab-${tab}`;
  const panelId = `cc-${variant}-tabpanel`;

  const title = en ? "Health Coach" : "健康教練";
  const busy = isBusy(phase);

  const figures = (
    <dl className="cc-figures" aria-label={en ? "Your figures" : "你的數據"}>
      <div className="cc-figure">
        <dt>{en ? "Recent load" : "近期負荷"}</dt>
        <dd>
          <span className="digits">{acuteLoad}</span>
          {primaryUnit && unitSuffix && <span className="cc-figure-unit">{unitSuffix}</span>}
        </dd>
      </div>
      <div className="cc-figure">
        <dt>{en ? "Baseline" : "基準"}</dt>
        <dd>
          <span className="digits">{chronicLoad}</span>
          {primaryUnit && unitSuffix && <span className="cc-figure-unit">{unitSuffix}</span>}
        </dd>
      </div>
      <div className="cc-figure">
        <dt>{en ? "Load ratio" : "負荷比"}</dt>
        <dd>
          <span className="digits">{loadRatio}</span>
        </dd>
      </div>
      <div className="cc-figure">
        <dt>{en ? "Conditions" : "天候"}</dt>
        <dd>
          {temperatureC === null ? (
            <span className="cc-figure-none">{en ? "Unavailable" : "暫無"}</span>
          ) : (
            <>
              <span className="digits">{Math.round(temperatureC)}°C</span>
              {speedLossPct !== null && (
                <span className="cc-figure-unit">
                  {en ? "pace " : "配速 "}
                  {speedLossPct > 0 ? "+" : ""}
                  {speedLossPct.toFixed(1)}%
                </span>
              )}
            </>
          )}
        </dd>
      </div>
    </dl>
  );

  return (
    <section
      className={`cc-panel cc-panel--${variant}`}
      aria-labelledby={variant === "page" ? titleId : undefined}
    >
      <header className="cc-head">
        <div className="cc-head-text">
          {variant === "page" ? (
            <h1 className="page-title cc-title" id={titleId}>
              {title}
            </h1>
          ) : (
            <h2 className="cc-title" id={titleId}>
              {title}
            </h2>
          )}
          <p className="cc-sub">
            {en
              ? "Reads your training records, published guidance and today's conditions."
              : "看你的訓練紀錄、專業指引與當下天候。"}
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            className="btn btn-ghost cc-close"
            onClick={onClose}
            aria-label={en ? "Close coach" : "關閉教練"}
          >
            <X size={18} aria-hidden="true" />
          </button>
        )}
      </header>

      <div className="cc-context">
        {figures}
        {variant === "page" && (
          <div className="cc-prompts-aside">
            <h2 className="cc-aside-title">{en ? "Try asking" : "可以這樣問"}</h2>
            <QuickPrompts prompts={quickPrompts} disabled={busy} onPick={(q) => void coach.send(q)} />
          </div>
        )}
      </div>

      <div className="cc-tabs" role="tablist" aria-label={title}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId(tab.id)}
            aria-selected={activeTab === tab.id}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onKeyDown={(event) => {
              const current = tabs.findIndex((item) => item.id === activeTab);
              const next = event.key === "ArrowRight" ? (current + 1) % tabs.length
                : event.key === "ArrowLeft" ? (current + tabs.length - 1) % tabs.length
                : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
              if (next === null) return;
              event.preventDefault();
              setActiveTab(tabs[next].id);
              document.getElementById(tabId(tabs[next].id))?.focus();
            }}
            aria-controls={panelId}
            className="cc-tab"
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        className="cc-body"
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(activeTab)}
        ref={scrollRef}
      >
        {activeTab === "chat" && <Conversation en={en} />}
        {activeTab === "injury" && <InjuryForm en={en} />}
        {activeTab === "guidance" && (
          <GuidanceLibrary
            en={en}
            initialBodyPart={coach.guidanceFocus?.bodyPart || reportContext?.bodyPart}
            initialPhase={coach.guidanceFocus?.phase}
          />
        )}
      </div>

      {activeTab === "chat" && (
        <footer className="cc-composer">
          {variant === "drawer" && (
            <QuickPrompts prompts={quickPrompts} disabled={busy} onPick={(q) => void coach.send(q)} />
          )}
          <form
            className="cc-input-row"
            onSubmit={(event) => {
              event.preventDefault();
              void coach.send();
            }}
          >
            <input
              type="text"
              className="input cc-input"
              value={coach.input}
              onChange={(event) => coach.setInput(event.target.value)}
              aria-label={en ? "Message to your coach" : "給教練的訊息"}
              placeholder={
                en
                  ? "Ask about today's session, your pace, or how you feel…"
                  : "問今天的課表、配速調整，或身體的狀況…"
              }
            />
            <button
              type="submit"
              className="btn btn-primary cc-send"
              disabled={!coach.input.trim() || busy}
            >
              <PaperPlaneTilt size={16} weight="bold" aria-hidden="true" />
              {en ? "Send" : "發送"}
            </button>
          </form>
          <p className="cc-privacy">
            {en
              ? "Messages and the training data needed to answer are processed by a cloud model; no names, emails or accounts are sent."
              : "對話與回答所需的訓練資料會送到雲端模型處理，不含姓名、Email 或帳號。"}
          </p>
        </footer>
      )}
    </section>
  );
}

function QuickPrompts({
  prompts,
  disabled,
  onPick,
}: {
  prompts: string[];
  disabled: boolean;
  onPick: (prompt: string) => void;
}) {
  return (
    <ul className="cc-prompts">
      {prompts.map((prompt) => (
        <li key={prompt}>
          <button
            type="button"
            className="cc-prompt"
            disabled={disabled}
            onClick={() => onPick(prompt)}
          >
            {prompt}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Conversation({ en }: { en: boolean }) {
  const coach = useCoachChat();
  const { phase, messages } = coach;
  const answerText = visibleText(phase);
  const citations = citationsOf(phase);
  const awaitingDecision = pendingProposal(phase);
  const { locale } = useLocale();

  return (
    <div className="cc-thread">
      {messages.map((message, index) => (
        <div key={index} className={message.role === "user" ? "cc-msg cc-msg--user" : "cc-msg"}>
          {message.role === "user" ? (
            <p className="cc-msg-text">{message.content}</p>
          ) : (
            <MarkdownMessage content={message.content} />
          )}
        </div>
      ))}

      {phase.kind !== "idle" && phase.kind !== "failed" && (
        <CoachThinking steps={stepsOfPhase(phase)} stillWorking={phase.kind === "thinking"} en={en} />
      )}

      {answerText && phase.kind === "failed" && (
        // Not an answer. The coach could not be reached, and saying so in the
        // same form a real answer uses would be dishonest.
        <div className="cc-unavailable" role="status">
          <WarningCircle size={18} weight="fill" aria-hidden="true" className="cc-unavailable-icon" />
          <div>
            <strong>{en ? "Coach unavailable" : "教練目前連線不上"}</strong>
            <p>{answerText}</p>
          </div>
        </div>
      )}

      {answerText && phase.kind !== "failed" && (
        <div className="cc-msg">
          <MarkdownMessage content={answerText} isStreaming={phase.kind === "streaming"} />
        </div>
      )}

      {answerText && phase.kind !== "failed" && citations.length > 0 && (
        <div className="cc-citations">
          <span className="cc-citations-label">{en ? "Based on" : "依據"}</span>
          {citations.map((citation) => (
            <button
              key={citation.evidenceId}
              type="button"
              className="cc-citation"
              onClick={() => coach.openCitation(citation)}
            >
              {citation.title}
            </button>
          ))}
        </div>
      )}

      {awaitingDecision && (
        <CoachProposalCard
          key={awaitingDecision.id}
          proposal={awaitingDecision}
          locale={locale}
          onAccept={() => coach.acceptProposal(awaitingDecision)}
          onShare={() => coach.shareProposal(awaitingDecision)}
          onDismiss={() => coach.dismissProposal(awaitingDecision)}
        />
      )}
    </div>
  );
}

function InjuryForm({ en }: { en: boolean }) {
  const { injury, setInjury, submitTriage } = useCoachChat();
  return (
    <div className="cc-injury">
      <fieldset className="cc-fieldset">
        <legend className="cc-legend">{en ? "Where does it feel off?" : "哪裡覺得不舒服？"}</legend>
        <div className="cc-choices">
          {BODY_PARTS.map((part) => (
            <Choice
              key={part}
              selected={injury.bodyPart === part}
              onClick={() => setInjury((current) => ({ ...current, bodyPart: part }))}
            >
              {part}
            </Choice>
          ))}
        </div>
      </fieldset>

      <fieldset className="cc-fieldset">
        <legend className="cc-legend">{en ? "How bad is it?" : "大概多嚴重？"}</legend>
        <div className="cc-choices cc-choices--even">
          {SEVERITIES.map((level) => (
            <Choice
              key={level}
              selected={injury.severity === level}
              onClick={() => setInjury((current) => ({ ...current, severity: level }))}
            >
              {level}
            </Choice>
          ))}
        </div>
      </fieldset>

      <fieldset className="cc-fieldset">
        <legend className="cc-legend cc-legend--critical">
          <WarningOctagon size={16} weight="bold" aria-hidden="true" />
          {en ? "Warning signs" : "需要特別留意的徵兆"}
        </legend>
        <label className="cc-check">
          <input
            type="checkbox"
            checked={injury.bonePain}
            onChange={(event) =>
              setInjury((current) => ({ ...current, bonePain: event.target.checked }))
            }
          />
          <span>局部骨頭壓痛，踩踏或負重時明顯加劇</span>
        </label>
        <label className="cc-check">
          <input
            type="checkbox"
            checked={injury.chestPain}
            onChange={(event) =>
              setInjury((current) => ({ ...current, chestPain: event.target.checked }))
            }
          />
          <span>運動中胸悶、呼吸異常困難或意識混亂</span>
        </label>
      </fieldset>

      <label className="cc-fieldset">
        <span className="cc-legend">{en ? "Anything else?" : "還想補充什麼？"}</span>
        <textarea
          className="input cc-note"
          value={injury.note}
          onChange={(event) => setInjury((current) => ({ ...current, note: event.target.value }))}
          placeholder="例如：跑完長距離後膝蓋下緣卡卡的，上下樓梯有點不適…"
        />
      </label>

      <button type="button" className="btn btn-primary btn-block cc-triage" onClick={submitTriage}>
        {en ? "Ask the coach about this" : "請教練看看"}
      </button>
    </div>
  );
}

function Choice({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="cc-choice" aria-pressed={selected} onClick={onClick}>
      {children}
    </button>
  );
}

function stepsOfPhase(phase: CoachPhase): ThinkingStep[] {
  switch (phase.kind) {
    case "thinking":
    case "streaming":
    case "proposal":
    case "answered":
      return phase.steps;
    default:
      return [];
  }
}
