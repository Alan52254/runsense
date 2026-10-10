import { useState, useRef, useEffect, useReducer } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  ChatCircleText,
  CloudSun,
  FirstAidKit,
  Gauge,
  Lightbulb,
  PaperPlaneTilt,
  WarningCircle,
  PencilSimple,
  Robot,
  WarningOctagon,
  X,
} from "@phosphor-icons/react";
import {
  acceptCoachProposal,
  dismissCoachProposal,
  shareCoachProposal,
  streamChatWithCoach,
} from "../data/apiClient.ts";
import type { CoachChatMessage } from "../data/apiClient.ts";
import { MarkdownMessage } from "./MarkdownMessage.tsx";
import { CoachThinking } from "./CoachThinking.tsx";
import { CoachProposalCard } from "./CoachProposalCard.tsx";
import { GuidanceLibrary } from "./GuidanceLibrary.tsx";
import {
  IDLE,
  citationsOf,
  coachPhaseReducer,
  isBusy,
  pendingProposal,
  visibleText,
} from "../lib/coachConversation.ts";
import type { CoachPhase, CoachProposal, ThinkingStep } from "../lib/coachConversation.ts";
import { useAuth } from "../state/AuthContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";

interface CoachChatModalProps {
  isOpen: boolean;
  onClose: () => void;
  reportContext?: {
    bodyPart: string;
    severityBand: string;
    guidanceSummary: string;
    nextSteps: string[];
  };
}

export function CoachChatModal({ isOpen, onClose, reportContext }: CoachChatModalProps) {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const { trainingLoad, liveWeather, refetchTrainingPlan } = useWorkspace();
  const en = locale === "en";

  const [activeTab, setActiveTab] = useState<"chat" | "injury" | "guidance">("chat");
  // Set when the Athlete opens a citation, so the guidance tab lands on
  // the passage they asked about rather than the top of the library.
  const [guidanceFocus, setGuidanceFocus] = useState<{ bodyPart: string; phase: string } | null>(
    null,
  );

  const [selectedBodyPart, setSelectedBodyPart] = useState("膝蓋 (Knee)");
  const [severity, setSeverity] = useState("輕微 (Mild)");
  const [hasBonePain, setHasBonePain] = useState(false);
  const [hasChestPain, setHasChestPain] = useState(false);
  const [injuryFreeText, setInjuryFreeText] = useState("");

  const [messages, setMessages] = useState<CoachChatMessage[]>([
    {
      role: "assistant",
      content: en
        ? "Hello — I am your RunSense coach. Ask me about today's session, how the weather changes your pace, how your recent load is tracking, or anything your body is telling you."
        : "你好，我是你的 RunSense 教練。今天該練什麼、天氣怎麼影響配速、最近的負荷狀況，或身體哪裡不舒服，都可以問我。",
    },
  ]);
  const [input, setInput] = useState("");

  // One value for the whole conversation: the coach cannot be thinking and
  // answering at once, and a proposal cannot wait on an answer still arriving.
  const [phase, dispatch] = useReducer(coachPhaseReducer, IDLE);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // The signed-in Athlete's own figures. Without enough observation they see
  // an em dash, never an invented number.
  const primaryUnit = trainingLoad.units[0] ?? null;
  const unitSuffix = primaryUnit?.unit === "AU" ? " AU" : "";
  const acuteLoadText = primaryUnit ? `${Math.round(primaryUnit.acuteLoad)}${unitSuffix}` : "—";
  const chronicLoadText = primaryUnit
    ? `${Math.round(primaryUnit.chronicLoad)}${unitSuffix}`
    : "—";
  const loadRatioText =
    primaryUnit && primaryUnit.loadRatio !== null ? primaryUnit.loadRatio.toFixed(2) : "—";
  const temperatureC =
    liveWeather && liveWeather.state !== "UNAVAILABLE" ? liveWeather.temperature_c : null;
  const speedLossPct = liveWeather?.speed_loss_pct_relative_to_normal ?? null;
  const conditionsText =
    temperatureC === null
      ? en
        ? "Conditions unavailable"
        : "天候資料暫無"
      : `${Math.round(temperatureC)}°C${
          speedLossPct === null
            ? ""
            : ` (${speedLossPct > 0 ? "+" : ""}${speedLossPct.toFixed(1)}%)`
        }`;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, phase]);

  useEffect(() => {
    if (!isOpen || !reportContext) return;
    setSelectedBodyPart(reportContext.bodyPart);
    setSeverity(reportContext.severityBand);
    setMessages((current) => {
      const contextMessage = en
        ? `Your latest assessment: ${reportContext.guidanceSummary}\n${reportContext.nextSteps.join("\n")}`
        : `你的最新評估結果：${reportContext.guidanceSummary}\n${reportContext.nextSteps.join("\n")}`;
      return current.some((message) => message.content === contextMessage)
        ? current
        : [...current, { role: "assistant", content: contextMessage }];
    });
  }, [en, isOpen, reportContext]);

  const bodyParts = [
    "膝蓋 (Knee)",
    "阿基里斯腱 (Achilles)",
    "足底筋膜 (Plantar)",
    "小腿脛骨 (Shin Splints)",
    "大腿後側 (Hamstring)",
    "髖關節 (Hip)",
  ];

  const humidityPct =
    liveWeather?.humidity_pct !== null && liveWeather?.humidity_pct !== undefined
      ? Math.round(liveWeather.humidity_pct)
      : null;

  const weatherPromptEn =
    temperatureC !== null && humidityPct !== null
      ? `It is ${Math.round(temperatureC)}°C and ${humidityPct}% humidity — how should I adjust my pace?`
      : "How should I adjust my pace for the current weather?";

  const weatherPromptZh =
    temperatureC !== null && humidityPct !== null
      ? `今天 ${Math.round(temperatureC)}°C、濕度 ${humidityPct}%，配速要怎麼調整？`
      : "依當前天候，配速要怎麼調整？";

  const quickPrompts = en
    ? [
        "What should I run today given my recent load?",
        weatherPromptEn,
        "I only have 30 minutes today.",
        "My calf feels tight after long runs — should I rest?",
      ]
    : [
        "依我最近的負荷，今天適合跑什麼？",
        weatherPromptZh,
        "我今天只有 30 分鐘。",
        "我小腿跑完有點緊，需要完全休息嗎？",
      ];

  if (!isOpen) return null;

  async function handleSend(textToSend?: string) {
    const text = (textToSend ?? input).trim();
    if (!text || isBusy(phase)) return;

    // The previous answer lives in the phase until now; fold it into the
    // transcript so it is not lost, and so the coach can see what it said.
    const priorAnswer = visibleText(phase).trim();
    const transcript: CoachChatMessage[] = priorAnswer
      ? [...messages, { role: "assistant", content: priorAnswer }]
      : messages;

    const userMsg: CoachChatMessage = { role: "user", content: text };
    const historyWithUser = [...transcript, userMsg];

    setMessages(historyWithUser);
    setInput("");
    setActiveTab("chat");
    dispatch({ type: "ASKED" });

    const unavailableText = en
      ? "Your coach cannot be reached right now. Your plan and any safety guidance you already have still stand."
      : "目前聯絡不上教練。你既有的課表與安全建議仍然有效；若有持續的急性疼痛，請諮詢專業醫師。";

    if (!auth?.accessToken) {
      dispatch({ type: "FAILED", text: unavailableText });
      return;
    }

    let sawText = false;
    try {
      await streamChatWithCoach(
        auth.accessToken,
        historyWithUser,
        (event) => {
          if (event.kind === "delta") {
            sawText = true;
            dispatch({ type: "DELTA", delta: event.delta });
          } else if (event.kind === "step") {
            const step = toThinkingStep(event.step);
            if (step) dispatch({ type: "STEP", step });
          } else if (event.kind === "proposal") {
            const proposal = toProposal(event.proposal);
            if (proposal) dispatch({ type: "PROPOSED", proposal });
          }
        },
        () => dispatch({ type: "SETTLED" }),
      );
      if (!sawText) dispatch({ type: "FAILED", text: unavailableText });
    } catch {
      // A dropped stream keeps whatever already arrived.
      if (sawText) dispatch({ type: "SETTLED" });
      else dispatch({ type: "FAILED", text: unavailableText });
    }
  }

  /** Null when applied; otherwise what to tell the Athlete. */
  async function handleAcceptProposal(proposal: CoachProposal): Promise<string | null> {
    if (!auth?.accessToken || !proposal.id) return null;
    const outcome = await acceptCoachProposal(auth.accessToken, proposal.id);
    if (!outcome.applied && outcome.reason === "COACH_SCHEDULED") {
      // the coach scheduled this day after the suggestion was made
      return en
        ? "Your coach has scheduled this day. Send this to your coach instead."
        : "教練已經排了這天的課表，無法直接套用。可以把建議傳給教練討論。";
    }
    dispatch({ type: "PROPOSAL_ACCEPTED" });
    // The Athlete's day has changed; the rest of the app should show it.
    await refetchTrainingPlan();
    return null;
  }

  /** Hands the suggestion to the coach; scheduling stays the coach's call. */
  async function handleShareProposal(proposal: CoachProposal): Promise<void> {
    if (!auth?.accessToken || !proposal.id) return;
    await shareCoachProposal(auth.accessToken, proposal.id);
  }

  function handleDismissProposal(proposal: CoachProposal) {
    dispatch({ type: "PROPOSAL_DISMISSED" });
    if (auth?.accessToken && proposal.id) {
      void dismissCoachProposal(auth.accessToken, proposal.id).catch(() => {
        // Declining is the Athlete's decision either way; a failed record of
        // it must not become their problem.
      });
    }
  }

  function handleTriageSubmit() {
    const prompt = `【身體回報】部位：${selectedBodyPart}，嚴重度：${severity}。${
      hasBonePain ? "（注意：負重時出現局部骨痛）" : ""
    }${hasChestPain ? "（注意：運動中胸悶或呼吸困難）" : ""}${
      injuryFreeText ? ` 自述症狀：${injuryFreeText}` : ""
    }。請評估我是否還能繼續跑步，並給我處置建議。`;
    handleSend(prompt);
  }

  const phaseSteps: ThinkingStep[] = stepsOfPhase(phase);
  const answerText = visibleText(phase);
  const citations = citationsOf(phase);
  const awaitingDecision = pendingProposal(phase);

  return createPortal(
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "var(--overlay)",
        backdropFilter: "blur(6px)",
        zIndex: 9999,
        display: "flex",
        justifyContent: "flex-end",
        animation: "fadeIn 0.2s ease-out",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "490px",
          height: "100%",
          // installed on an iPhone: clear of the status bar and home indicator
          paddingTop: "env(safe-area-inset-top)",
          paddingBottom: "env(safe-area-inset-bottom)",
          boxSizing: "border-box",
          backgroundColor: "var(--surface)",
          borderLeft: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow-lg)",
          color: "var(--text)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            padding: "16px 20px",
            backgroundColor: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <CoachAvatar busy={isBusy(phase)} />
            <div>
              <div style={{ fontWeight: 750, fontSize: 15, letterSpacing: 0.2 }}>
                {en ? "RunSense Coach" : "RunSense 智慧教練"}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {en
                  ? "Your training data, published guidance, today's conditions"
                  : "看你的訓練資料、專業指引與當下天候"}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={en ? "Close coach" : "關閉教練"}
            style={{
              background: "transparent",
              border: "1px solid var(--border)",
              borderRadius: 6,
              color: "var(--text-muted)",
              width: 34,
              height: 34,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div
          style={{
            display: "flex",
            backgroundColor: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <TabButton
            active={activeTab === "chat"}
            onClick={() => setActiveTab("chat")}
            icon={<ChatCircleText size={15} weight={activeTab === "chat" ? "bold" : "regular"} />}
            label={en ? "Ask" : "問教練"}
          />
          <TabButton
            active={activeTab === "injury"}
            onClick={() => setActiveTab("injury")}
            icon={<FirstAidKit size={15} weight={activeTab === "injury" ? "bold" : "regular"} />}
            label={en ? "How you feel" : "身體回報"}
          />
          <TabButton
            active={activeTab === "guidance"}
            onClick={() => setActiveTab("guidance")}
            icon={<BookOpen size={15} weight={activeTab === "guidance" ? "bold" : "regular"} />}
            label={en ? "Guidance" : "專業指引"}
          />
        </div>

        <div
          style={{
            padding: "8px 16px",
            backgroundColor: "var(--accent-soft)",
            borderBottom: "1px solid var(--accent-ring)",
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11.5,
            fontWeight: 600,
            color: "var(--text)",
          }}
        >
          <span>
            {en ? "Recent" : "近期負荷"}: <strong>{acuteLoadText}</strong>
          </span>
          <span>
            {en ? "Baseline" : "基準"}: <strong>{chronicLoadText}</strong>
          </span>
          <span>
            {en ? "Ratio" : "負荷比"}:{" "}
            <strong style={{ color: "var(--accent)" }}>{loadRatioText}</strong>
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CloudSun size={14} aria-hidden="true" /> {conditionsText}
          </span>
        </div>

        {activeTab === "chat" && (
          <>
            <div
              ref={scrollRef}
              style={{
                flex: 1,
                padding: "16px",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              {messages.map((m, i) => (
                <div
                  key={i}
                  style={{
                    alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: m.role === "user" ? "85%" : "96%",
                    padding: "12px 16px",
                    borderRadius:
                      m.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                    backgroundColor: m.role === "user" ? "var(--accent)" : "var(--surface-2)",
                    border: m.role === "user" ? "none" : "1px solid var(--border)",
                    color: m.role === "user" ? "var(--accent-on)" : "var(--text)",
                    boxShadow: "var(--shadow-sm)",
                  }}
                >
                  {m.role === "user" ? (
                    <div style={{ fontSize: 13.5, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                      {m.content}
                    </div>
                  ) : (
                    <MarkdownMessage content={m.content} />
                  )}
                </div>
              ))}

              {phase.kind !== "idle" && phase.kind !== "failed" && (
                <CoachThinking
                  steps={phaseSteps}
                  stillWorking={phase.kind === "thinking"}
                  en={en}
                />
              )}

              {answerText && phase.kind === "failed" && (
                // Not an answer. The coach could not be reached, and saying so
                // in the same bubble a real answer uses would be dishonest.
                <div
                  role="status"
                  style={{
                    alignSelf: "stretch",
                    padding: "12px 14px",
                    borderRadius: 12,
                    backgroundColor: "var(--warning-soft, var(--surface-sunken))",
                    border: "1px solid var(--warning-ring, var(--border))",
                    display: "flex",
                    gap: 10,
                    alignItems: "flex-start",
                  }}
                >
                  <WarningCircle
                    size={18}
                    weight="fill"
                    color="var(--warning, var(--text-muted))"
                    aria-hidden="true"
                    style={{ flexShrink: 0, marginTop: 1 }}
                  />
                  <div>
                    <div style={{ fontWeight: 750, fontSize: 13, marginBottom: 3 }}>
                      {en ? "Coach unavailable" : "教練目前連線不上"}
                    </div>
                    <div style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--text-2)" }}>
                      {answerText}
                    </div>
                  </div>
                </div>
              )}

              {answerText && phase.kind !== "failed" && (
                <div
                  style={{
                    alignSelf: "flex-start",
                    maxWidth: "96%",
                    padding: "12px 16px",
                    borderRadius: "16px 16px 16px 4px",
                    backgroundColor: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    boxShadow: "var(--shadow-sm)",
                  }}
                >
                  <MarkdownMessage
                    content={answerText}
                    isStreaming={phase.kind === "streaming"}
                  />
                </div>
              )}

              {answerText && phase.kind !== "failed" && citations.length > 0 && (
                <div
                  style={{
                    alignSelf: "flex-start",
                    maxWidth: "96%",
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                  }}
                >
                  <span style={{ fontSize: 11.5, color: "var(--text-muted)", alignSelf: "center" }}>
                    {en ? "Based on:" : "依據："}
                  </span>
                  {citations.map((citation) => (
                    <button
                      key={citation.evidenceId}
                      type="button"
                      onClick={() => {
                        setGuidanceFocus({
                          bodyPart: citation.bodyParts[0] ?? "",
                          phase: citation.phase ?? "",
                        });
                        setActiveTab("guidance");
                      }}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 12,
                        border: "1px solid var(--accent-ring)",
                        backgroundColor: "var(--accent-soft)",
                        color: "var(--accent-ink)",
                        fontSize: 11,
                        fontWeight: 650,
                        cursor: "pointer",
                        maxWidth: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {citation.title}
                    </button>
                  ))}
                </div>
              )}

              {awaitingDecision && (
                <CoachProposalCard
                  proposal={awaitingDecision}
                  locale={locale}
                  onAccept={() => handleAcceptProposal(awaitingDecision)}
                  onShare={() => handleShareProposal(awaitingDecision)}
                  onDismiss={() => handleDismissProposal(awaitingDecision)}
                />
              )}
            </div>

            <div
              style={{
                padding: "8px 12px",
                display: "flex",
                gap: 6,
                overflowX: "auto",
                borderTop: "1px solid var(--border)",
                backgroundColor: "var(--surface)",
              }}
            >
              {quickPrompts.map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSend(q)}
                  style={{
                    whiteSpace: "nowrap",
                    padding: "5px 10px",
                    borderRadius: 16,
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--surface-sunken)",
                    color: "var(--text-2)",
                    fontSize: 11.5,
                    cursor: "pointer",
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <Lightbulb size={13} aria-hidden="true" /> {q}
                  </span>
                </button>
              ))}
            </div>

            <div
              style={{
                padding: "12px 14px",
                borderTop: "1px solid var(--border)",
                display: "flex",
                gap: 8,
                backgroundColor: "var(--surface)",
              }}
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSend();
                }}
                placeholder={
                  en
                    ? "Ask about today's session, your pace, or how you feel…"
                    : "問今天的課表、配速調整，或身體的狀況…"
                }
                style={{
                  flex: 1,
                  padding: "10px 14px",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  backgroundColor: "var(--surface)",
                  color: "var(--text)",
                  fontSize: 13.5,
                  outline: "none",
                }}
              />
              <button
                type="button"
                onClick={() => handleSend()}
                disabled={!input.trim() || isBusy(phase)}
                style={{
                  padding: "10px 18px",
                  borderRadius: 10,
                  backgroundColor: "var(--accent)",
                  color: "var(--accent-on)",
                  fontWeight: 700,
                  border: "none",
                  cursor: "pointer",
                  fontSize: 13.5,
                  opacity: !input.trim() || isBusy(phase) ? 0.6 : 1,
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <PaperPlaneTilt size={15} weight="bold" aria-hidden="true" />
                  {en ? "Send" : "發送"}
                </span>
              </button>
            </div>
          </>
        )}

        {activeTab === "injury" && (
          <div
            style={{
              flex: 1,
              padding: "18px",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div>
              <SectionTitle
                icon={<FirstAidKit size={18} weight="bold" color="var(--accent)" />}
                text={en ? "Where does it feel off?" : "哪裡覺得不舒服？"}
              />
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {bodyParts.map((part) => (
                  <Chip
                    key={part}
                    label={part}
                    selected={selectedBodyPart === part}
                    onClick={() => setSelectedBodyPart(part)}
                  />
                ))}
              </div>
            </div>

            <div>
              <SectionTitle
                icon={<Gauge size={18} weight="bold" color="var(--accent)" />}
                text={en ? "How bad is it?" : "大概多嚴重？"}
              />
              <div style={{ display: "flex", gap: 8 }}>
                {["輕微 (Mild)", "中度 (Moderate)", "嚴重 (Severe)"].map((s) => (
                  <Chip
                    key={s}
                    label={s}
                    selected={severity === s}
                    grow
                    onClick={() => setSeverity(s)}
                  />
                ))}
              </div>
            </div>

            <div>
              <SectionTitle
                icon={<WarningOctagon size={18} weight="bold" color="var(--critical)" />}
                text={en ? "Warning signs" : "需要特別留意的徵兆"}
                critical
              />
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  marginBottom: 6,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={hasBonePain}
                  onChange={(e) => setHasBonePain(e.target.checked)}
                />
                <span>局部骨頭壓痛，踩踏或負重時明顯加劇</span>
              </label>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={hasChestPain}
                  onChange={(e) => setHasChestPain(e.target.checked)}
                />
                <span>運動中胸悶、呼吸異常困難或意識混亂</span>
              </label>
            </div>

            <div>
              <SectionTitle
                icon={<PencilSimple size={18} weight="bold" color="var(--accent)" />}
                text={en ? "Anything else?" : "還想補充什麼？"}
              />
              <textarea
                value={injuryFreeText}
                onChange={(e) => setInjuryFreeText(e.target.value)}
                placeholder="例如：跑完長距離後膝蓋下緣卡卡的，上下樓梯有點不適…"
                style={{
                  width: "100%",
                  height: 70,
                  padding: "10px",
                  borderRadius: 10,
                  backgroundColor: "var(--surface-sunken)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  fontSize: 13,
                  resize: "none",
                  outline: "none",
                }}
              />
            </div>

            <button
              type="button"
              onClick={handleTriageSubmit}
              style={{
                backgroundColor: "var(--accent)",
                color: "var(--accent-on)",
                padding: "13px",
                borderRadius: 12,
                border: "none",
                fontWeight: 750,
                fontSize: 14,
                cursor: "pointer",
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                gap: 8,
                marginTop: "auto",
              }}
            >
              <FirstAidKit size={18} weight="bold" aria-hidden="true" />
              <span>{en ? "Ask the coach about this" : "請教練看看"}</span>
            </button>
          </div>
        )}

        {activeTab === "guidance" && (
          <div style={{ flex: 1, padding: "18px", overflowY: "auto" }}>
            <GuidanceLibrary
              en={en}
              initialBodyPart={guidanceFocus?.bodyPart || reportContext?.bodyPart}
              initialPhase={guidanceFocus?.phase}
            />
          </div>
        )}
      </div>
    </div>,
    document.body,
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

function CoachAvatar({ busy }: { busy: boolean }) {
  return (
    <div
      style={{
        width: 38,
        height: 38,
        borderRadius: 11,
        backgroundColor: "var(--accent-soft)",
        border: "1px solid var(--accent-ring)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--accent)",
        position: "relative",
      }}
    >
      <Robot size={21} weight="fill" aria-hidden="true" />
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          right: -2,
          bottom: -2,
          width: 10,
          height: 10,
          borderRadius: "50%",
          border: "2px solid var(--surface-2)",
          backgroundColor: busy ? "var(--accent)" : "var(--good, #16a34a)",
        }}
      />
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        padding: "11px 8px",
        border: "none",
        borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
        backgroundColor: "transparent",
        color: active ? "var(--accent)" : "var(--text-muted)",
        fontWeight: active ? 700 : 500,
        fontSize: 12.5,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function SectionTitle({
  icon,
  text,
  critical,
}: {
  icon: ReactNode;
  text: string;
  critical?: boolean;
}) {
  return (
    <div
      style={{
        fontWeight: 800,
        fontSize: 14.5,
        marginBottom: 8,
        display: "flex",
        alignItems: "center",
        gap: 7,
        color: critical ? "var(--critical)" : undefined,
      }}
    >
      {icon}
      <span>{text}</span>
    </div>
  );
}

function Chip({
  label,
  selected,
  grow,
  onClick,
}: {
  label: string;
  selected: boolean;
  grow?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: grow ? 1 : undefined,
        padding: "7px 12px",
        borderRadius: 10,
        border: selected ? "2px solid var(--accent)" : "1px solid var(--border)",
        backgroundColor: selected ? "var(--accent-soft)" : "var(--surface-sunken)",
        color: selected ? "var(--accent-ink)" : "var(--text)",
        fontWeight: selected ? 800 : 600,
        fontSize: 12.5,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}

function toThinkingStep(raw: Record<string, unknown>): ThinkingStep | null {
  switch (raw.step) {
    case "READ_TRAINING_LOAD":
      return {
        kind: "READ_TRAINING_LOAD",
        observationDays: Number(raw.observation_days ?? 0),
        loadRatio: typeof raw.load_ratio === "number" ? raw.load_ratio : null,
      };
    case "REVIEWED_GUIDANCE":
      return {
        kind: "REVIEWED_GUIDANCE",
        count: Number(raw.count ?? 0),
        citations: (Array.isArray(raw.citations) ? raw.citations : []).map((entry) => {
          const citation = entry as Record<string, unknown>;
          return {
            evidenceId: String(citation.evidence_id ?? ""),
            title: String(citation.title ?? ""),
            publisher: String(citation.publisher ?? ""),
            sourceUrl: String(citation.source_url ?? ""),
            bodyParts: Array.isArray(citation.body_parts)
              ? citation.body_parts.map(String)
              : [],
            phase: typeof citation.phase === "string" ? citation.phase : null,
          };
        }),
      };
    case "CONSIDERED_OPTIONS":
      return {
        kind: "CONSIDERED_OPTIONS",
        count: Number(raw.count ?? 0),
        personalised: Boolean(raw.personalised),
      };
    default:
      return null;
  }
}

function toProposal(raw: Record<string, unknown>): CoachProposal | null {
  const facts = (raw.facts ?? {}) as Record<string, unknown>;
  const candidates = Array.isArray(raw.candidates) ? raw.candidates : [];
  if (candidates.length === 0) return null;

  return {
    id: typeof raw.id === "string" ? raw.id : null,
    label: String(raw.label ?? ""),
    changedFacts: Array.isArray(raw.changed_facts) ? raw.changed_facts.map(String) : [],
    accepted: Boolean(raw.accepted),
    abstained: Boolean(raw.abstained),
    confidence: typeof raw.confidence === "number" ? raw.confidence : null,
    speedLossPct: typeof raw.speed_loss_pct === "number" ? raw.speed_loss_pct : null,
    pacingIsExtrapolated: Boolean(raw.pacing_is_extrapolated),
    coachAssigned: Array.isArray(raw.coach_assigned) ? raw.coach_assigned.map(String) : [],
    // absent (an older backend): applying is what it always allowed
    selfApplyAllowed: raw.self_apply_allowed !== false,
    facts: {
      localDate: String(facts.local_date ?? ""),
      temperatureC: typeof facts.temperature_c === "number" ? facts.temperature_c : null,
      humidityPct: typeof facts.humidity_pct === "number" ? facts.humidity_pct : null,
      availableMinutes:
        typeof facts.available_minutes === "number" ? facts.available_minutes : null,
      reportedBodyPart:
        typeof facts.reported_body_part === "string" ? facts.reported_body_part : null,
      reportedSeverityBand:
        typeof facts.reported_severity_band === "string" ? facts.reported_severity_band : null,
    },
    candidates: candidates.map((entry) => {
      const candidate = entry as Record<string, unknown>;
      return {
        candidateId: String(candidate.candidate_id ?? ""),
        workoutType: String(candidate.workout_type ?? ""),
        durationMinutes: Number(candidate.duration_minutes ?? 0),
        distanceKm: Number(candidate.distance_km ?? 0),
        runningAllowed: Boolean(candidate.running_allowed),
      };
    }),
  };
}
