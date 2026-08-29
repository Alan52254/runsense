import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  Article,
  Books,
  ChatCircleText,
  CloudSun,
  FirstAidKit,
  Gauge,
  Lightbulb,
  Lightning,
  PaperPlaneTilt,
  PencilSimple,
  WarningOctagon,
  X,
} from "@phosphor-icons/react";
import { chatWithCoach } from "../data/apiClient.ts";
import type { CoachChatMessage } from "../data/apiClient.ts";
import { MarkdownMessage } from "./MarkdownMessage.tsx";
import { useAuth } from "../state/AuthContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";

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
  const en = locale === "en";

  const [activeTab, setActiveTab] = useState<"chat" | "injury" | "rag">("chat");

  // Injury selection state
  const [selectedBodyPart, setSelectedBodyPart] = useState("膝蓋 (Knee)");
  const [severity, setSeverity] = useState("輕微 (Mild)");
  const [hasBonePain, setHasBonePain] = useState(false);
  const [hasChestPain, setHasChestPain] = useState(false);
  const [injuryFreeText, setInjuryFreeText] = useState("");

  const [messages, setMessages] = useState<CoachChatMessage[]>([
    {
      role: "assistant",
      content: en
        ? "Hello! I am your RunSense Sports Physiology & Health Coach. Ask about today's training plan, pacing adjustments, ACWR load balance, or body status."
        : "你好！我是 RunSense 專業運動生理與跑步健康教練。你可以隨時詢問今日課表、天候補償配速換算、ACWR 負荷狀態或身體不適處置建議。",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isStreaming]);

  useEffect(() => {
    if (!isOpen || !reportContext) return;
    setSelectedBodyPart(reportContext.bodyPart);
    setSeverity(reportContext.severityBand);
    setMessages((current) => {
      const contextMessage = en
        ? `Your latest triage assessment: ${reportContext.guidanceSummary}\n${reportContext.nextSteps.join("\n")}`
        : `你的最新分流評估結果：${reportContext.guidanceSummary}\n${reportContext.nextSteps.join("\n")}`;
      return current.some((message) => message.content === contextMessage)
        ? current
        : [...current, { role: "assistant", content: contextMessage }];
    });
  }, [en, isOpen, reportContext]);

  const bodyParts = ["膝蓋 (Knee)", "阿基里斯腱 (Achilles)", "足底筋膜 (Plantar)", "小腿脛骨 (Shin Splints)", "大腿後側 (Hamstring)", "髖關節 (Hip)"];

  const quickPrompts = en
    ? [
        "What workout should I run today based on my ACWR 1.52?",
        "How should I adjust pace in 28°C humid weather?",
        "My calf feels tight after long runs, should I rest?",
      ]
    : [
        "依據目前 1.52 的負荷比，今天建議跑什麼強度？",
        "今天氣溫 28°C 濕度 75%，配速應該如何換算調整？",
        "我小腿在跑後有些微緊繃，需要完全停跑嗎？",
      ];

  if (!isOpen) return null;

  async function handleSend(textToSend?: string) {
    const text = (textToSend ?? input).trim();
    if (!text || loading || isStreaming) return;

    const userMsg: CoachChatMessage = { role: "user", content: text };
    const historyWithUser = [...messages, userMsg];

    setMessages(historyWithUser);
    setInput("");
    setActiveTab("chat");
    setLoading(true);

    try {
      let fullResponseText = "";
      if (auth?.accessToken) {
        try {
          const res = await chatWithCoach(auth.accessToken, historyWithUser);
          if (res?.response) {
            fullResponseText = res.response;
          }
        } catch {
          // fallback
        }
      }

      if (!fullResponseText) fullResponseText = en
        ? "The RunSense Coach is temporarily unavailable. Please keep the current safety triage guidelines."
        : "RunSense 運動生理教練目前無法回覆。請維持既有的安全分流建議；若有持續急性疼痛請諮詢專業醫師。";

      // Smooth typewriter progressive streaming
      setLoading(false);
      setIsStreaming(true);
      let currentLen = 0;
      const step = 4;
      const timer = setInterval(() => {
        currentLen += step;
        if (currentLen >= fullResponseText.length) {
          clearInterval(timer);
          setMessages([...historyWithUser, { role: "assistant", content: fullResponseText }]);
          setIsStreaming(false);
        } else {
          setMessages([
            ...historyWithUser,
            { role: "assistant", content: fullResponseText.slice(0, currentLen) },
          ]);
        }
      }, 18);
    } catch {
      setLoading(false);
      setIsStreaming(false);
    }
  }

  function handleTriageSubmit() {
    const prompt = `【身體感知回報】部位：${selectedBodyPart}，嚴重度：${severity}。${
      hasBonePain ? "（注意：出現負重時局部骨痛警訊）" : ""
    }${hasChestPain ? "（注意：運動中胸悶氣喘症狀）" : ""}${
      injuryFreeText ? ` 自述症狀：${injuryFreeText}` : ""
    }。請依據醫學實證 RAG 資料庫評估是否能繼續跑步，並給予處置建議。`;
    handleSend(prompt);
  }

  return createPortal(
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
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
          backgroundColor: "var(--surface)",
          borderLeft: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow-lg)",
          color: "var(--text)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modern Athletic Clinical Header */}
        <div
          style={{
            padding: "16px 20px",
            backgroundColor: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
            color: "var(--text)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 8,
                backgroundColor: "var(--accent-soft)",
                border: "1px solid var(--accent-ring)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--accent)",
              }}
            >
              <ChatCircleText size={20} weight="bold" aria-hidden="true" />
            </div>
            <div>
              <div style={{ fontWeight: 750, fontSize: 15, letterSpacing: 0.2 }}>
                {en ? "RunSense Sports Physiology Coach" : "RunSense 運動生理與臨床實證教練"}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {en ? "Graph RAG Evidence Base · Dynamic Load Model" : "Graph RAG 實證知識庫 × 負荷動態模型"}
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

        {/* 3-Tab Selector */}
        <div
          style={{
            display: "flex",
            backgroundColor: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <button
            onClick={() => setActiveTab("chat")}
            style={{
              flex: 1,
              padding: "11px 8px",
              border: "none",
              borderBottom: activeTab === "chat" ? "2px solid var(--accent)" : "2px solid transparent",
              backgroundColor: "transparent",
              color: activeTab === "chat" ? "var(--accent)" : "var(--text-muted)",
              fontWeight: activeTab === "chat" ? 700 : 500,
              fontSize: 12.5,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <ChatCircleText size={15} weight={activeTab === "chat" ? "bold" : "regular"} />
            <span>{en ? "Consult" : "對話諮詢"}</span>
          </button>
          <button
            onClick={() => setActiveTab("injury")}
            style={{
              flex: 1,
              padding: "11px 8px",
              border: "none",
              borderBottom: activeTab === "injury" ? "2px solid var(--accent)" : "2px solid transparent",
              backgroundColor: "transparent",
              color: activeTab === "injury" ? "var(--accent)" : "var(--text-muted)",
              fontWeight: activeTab === "injury" ? 700 : 500,
              fontSize: 12.5,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <FirstAidKit size={15} weight={activeTab === "injury" ? "bold" : "regular"} />
            <span>{en ? "Triage" : "傷痛快篩"}</span>
          </button>
          <button
            onClick={() => setActiveTab("rag")}
            style={{
              flex: 1,
              padding: "11px 8px",
              border: "none",
              borderBottom: activeTab === "rag" ? "2px solid var(--accent)" : "2px solid transparent",
              backgroundColor: "transparent",
              color: activeTab === "rag" ? "var(--accent)" : "var(--text-muted)",
              fontWeight: activeTab === "rag" ? 700 : 500,
              fontSize: 12.5,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <Books size={15} weight={activeTab === "rag" ? "bold" : "regular"} />
            <span>{en ? "Evidence Base" : "實證文獻庫"}</span>
          </button>
        </div>

        {/* Live Telemetry Ribbon */}
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
          <span>短期負荷: <strong>320 AU</strong></span>
          <span>基準: <strong>210 AU</strong></span>
          <span>ACWR: <strong style={{ color: "var(--accent)" }}>1.52</strong></span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CloudSun size={14} aria-hidden="true" /> 28°C (+8s/km)
          </span>
        </div>

        {/* TAB 1: AI Chat */}
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
              {messages.map((m, i) => {
                const isUser = m.role === "user";
                const isCurrentAssistantStreaming = isStreaming && !isUser && i === messages.length - 1;

                if (!isUser && !m.content && loading) {
                  return null;
                }

                return (
                  <div
                    key={i}
                    style={{
                      alignSelf: isUser ? "flex-end" : "flex-start",
                      maxWidth: isUser ? "85%" : "96%",
                      padding: "12px 16px",
                      borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                      backgroundColor: isUser ? "var(--accent)" : "var(--surface-2)",
                      border: isUser ? "none" : "1px solid var(--border)",
                      color: isUser ? "var(--accent-on)" : "var(--text)",
                      boxShadow: "var(--shadow-sm)",
                    }}
                  >
                    {isUser ? (
                      <div style={{ fontSize: 13.5, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ) : (
                      <MarkdownMessage content={m.content} isStreaming={isCurrentAssistantStreaming} />
                    )}
                  </div>
                );
              })}
              {loading && !messages[messages.length - 1]?.content && (
                <div
                  style={{
                    alignSelf: "flex-start",
                    padding: "10px 16px",
                    borderRadius: "16px 16px 16px 4px",
                    backgroundColor: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    color: "var(--accent-ink)",
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Lightning size={15} aria-hidden="true" />
                    {en ? "Analyzing sports physiology with Graph RAG..." : "正在以運動生理與 Graph RAG 知識庫分析建議…"}
                  </span>
                </div>
              )}
            </div>

            {/* Quick Prompts */}
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

            {/* Chat Input */}
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
                placeholder={en ? "Ask coach about workout, knee pain, pacing..." : "向 RunSense 教練提問（配速換算、膝蓋不適、負荷調配）…"}
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
                disabled={!input.trim() || loading}
                style={{
                  padding: "10px 18px",
                  borderRadius: 10,
                  backgroundColor: "var(--accent)",
                  color: "var(--accent-on)",
                  fontWeight: 700,
                  border: "none",
                  cursor: "pointer",
                  fontSize: 13.5,
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

        {/* TAB 2: Body Status & Injury Triage Integration */}
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
              <div style={{ fontWeight: 800, fontSize: 14.5, marginBottom: 8, display: "flex", alignItems: "center", gap: 7 }}>
                <FirstAidKit size={18} weight="bold" color="var(--accent)" aria-hidden="true" />
                <span>{en ? "Select Discomfort / Soreness Area" : "選擇身體痠痛/不適部位"}</span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {bodyParts.map((part) => (
                  <button
                    key={part}
                    onClick={() => setSelectedBodyPart(part)}
                    style={{
                      padding: "7px 12px",
                      borderRadius: 10,
                      border: selectedBodyPart === part ? "2px solid var(--accent)" : "1px solid var(--border)",
                      backgroundColor: selectedBodyPart === part ? "var(--accent-soft)" : "var(--surface-sunken)",
                      color: selectedBodyPart === part ? "var(--accent-ink)" : "var(--text)",
                      fontWeight: selectedBodyPart === part ? 800 : 600,
                      fontSize: 12.5,
                      cursor: "pointer",
                    }}
                  >
                    {part}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 800, fontSize: 14.5, marginBottom: 8, display: "flex", alignItems: "center", gap: 7 }}>
                <Gauge size={18} weight="bold" color="var(--accent)" aria-hidden="true" />
                <span>{en ? "Severity Assessment" : "嚴重程度評估"}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {["輕微 (Mild)", "中度 (Moderate)", "嚴重 (Severe)"].map((s) => (
                  <button
                    key={s}
                    onClick={() => setSeverity(s)}
                    style={{
                      flex: 1,
                      padding: "8px",
                      borderRadius: 10,
                      border: severity === s ? "2px solid var(--accent)" : "1px solid var(--border)",
                      backgroundColor: severity === s ? "var(--accent-soft)" : "var(--surface-sunken)",
                      color: severity === s ? "var(--accent-ink)" : "var(--text)",
                      fontWeight: 700,
                      fontSize: 12,
                      cursor: "pointer",
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 800, fontSize: 14.5, marginBottom: 8, color: "var(--critical)", display: "flex", alignItems: "center", gap: 7 }}>
                <WarningOctagon size={18} weight="bold" color="var(--critical)" aria-hidden="true" />
                <span>{en ? "Red Flags Screening" : "紅旗警訊篩檢 (Red Flags)"}</span>
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginBottom: 6, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={hasBonePain}
                  onChange={(e) => setHasBonePain(e.target.checked)}
                />
                <span>局部骨痛且負重/踩踏時明顯加劇 (AAOS 骨應力警訊)</span>
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={hasChestPain}
                  onChange={(e) => setHasChestPain(e.target.checked)}
                />
                <span>運動中出現胸悶、呼吸異常困難或意識混亂 (ACSM 警訊)</span>
              </label>
            </div>

            <div>
              <div style={{ fontWeight: 800, fontSize: 14.5, marginBottom: 6, display: "flex", alignItems: "center", gap: 7 }}>
                <PencilSimple size={18} weight="bold" color="var(--accent)" aria-hidden="true" />
                <span>{en ? "Subjective Symptoms Note" : "自述症狀補充"}</span>
              </div>
              <textarea
                value={injuryFreeText}
                onChange={(e) => setInjuryFreeText(e.target.value)}
                placeholder="例如：跑完長距離後膝蓋下緣卡卡的，上下樓梯有些微不適…"
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
              <span>{en ? "Submit to RunSense Coach for RAG Evaluation" : "送交 RunSense 教練進行 RAG 實證評估"}</span>
            </button>
          </div>
        )}

        {/* TAB 3: RAG Clinical Evidence Passages */}
        {activeTab === "rag" && (
          <div
            style={{
              flex: 1,
              padding: "18px",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
              {en ? "RunSense integrates international sports medicine guidelines. The coach grounds all recommendations on peer-reviewed evidence:" : "RunSense 內建國際運動醫學與運動科學實證資料庫，教練所有回覆均對齊以下同儕審查文獻："}
            </div>

            <div
              style={{
                backgroundColor: "var(--surface-sunken)",
                padding: 14,
                borderRadius: 12,
                border: "1px solid var(--border)",
              }}
            >
              <div style={{ fontWeight: 800, fontSize: 13.5, color: "var(--accent-ink)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                <Article size={16} weight="bold" /> Tim Gabbett (2016) ACWR 運動負荷悖論
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>
                British Journal of Sports Medicine (BJSM)
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-2)" }}>
                證實 ACWR 短長期負荷比在 0.8 ~ 1.3 之間為體能發展甜蜜區，受傷機率最低；當比值超過 1.5 時，受傷相對風險增加 2~4 倍。
              </div>
            </div>

            <div
              style={{
                backgroundColor: "var(--surface-sunken)",
                padding: 14,
                borderRadius: 12,
                border: "1px solid var(--border)",
              }}
            >
              <div style={{ fontWeight: 800, fontSize: 13.5, color: "var(--accent-ink)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                <Article size={16} weight="bold" /> Dubois & Esculier (2020) 軟組織處理 PEACE & LOVE
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>
                British Journal of Sports Medicine (BJSM)
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-2)" }}>
                取代過時的 RICE 原則，提倡急性期保護 (Protect)、適度負重 (Optimal Loading) 與血管新生 (Vascularisation)，避免過度冰敷阻礙修復。
              </div>
            </div>

            <div
              style={{
                backgroundColor: "var(--surface-sunken)",
                padding: 14,
                borderRadius: 12,
                border: "1px solid var(--border)",
              }}
            >
              <div style={{ fontWeight: 800, fontSize: 13.5, color: "var(--accent-ink)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                <Article size={16} weight="bold" /> AAOS OrthoInfo 骨應力骨折警訊指引
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>
                American Academy of Orthopaedic Surgeons
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-2)" }}>
                若出現局部單點骨頭壓痛且負重踩踏時劇烈疼痛，嚴禁繼續跑步，需立即啟動醫療分流進行影像檢查。
              </div>
            </div>

            <div
              style={{
                backgroundColor: "var(--surface-sunken)",
                padding: 14,
                borderRadius: 12,
                border: "1px solid var(--border)",
              }}
            >
              <div style={{ fontWeight: 800, fontSize: 13.5, color: "var(--accent-ink)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                <Article size={16} weight="bold" /> ACSM 濕熱環境運動安全與補償指引
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>
                American College of Sports Medicine
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-2)" }}>
                氣溫高於 28°C 且濕度大於 70% 時，心血管散熱負荷大幅提升，每公里需主動降低 8~30 秒以維持核心體溫平衡。
              </div>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
