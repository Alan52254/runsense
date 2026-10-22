/* The one health-coach conversation.
 *
 * The header drawer and the 健康教練 page (in both workspaces) are frames
 * around the same panel; this provider owns everything they show, so a
 * message sent in one is in the other, and 身體感知 hands its report to the
 * same conversation instead of starting a second one. Mounted above both
 * workspaces' routes so switching 選手／教練 keeps the conversation; it is
 * keyed on the signed-in user, so signing out ends it.
 */

import { createContext, useCallback, useContext, useMemo, useReducer, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import {
  acceptCoachProposal,
  dismissCoachProposal,
  shareCoachProposal,
  streamChatWithCoach,
} from "../data/apiClient.ts";
import type { CoachChatMessage } from "../data/apiClient.ts";
import { IDLE, coachPhaseReducer, isBusy, visibleText } from "../lib/coachConversation.ts";
import type { Citation, CoachPhase, CoachProposal } from "../lib/coachConversation.ts";
import { appendOnce, reportContextMessage } from "../lib/coachChatSession.ts";
import type { CoachReportContext } from "../lib/coachChatSession.ts";
import { toProposal, toThinkingStep } from "../lib/coachWire.ts";
import { useAuth } from "./AuthContext.tsx";
import { useLocale } from "./LocaleContext.tsx";
import { useWorkspace } from "./WorkspaceContext.tsx";

export type { CoachReportContext } from "../lib/coachChatSession.ts";

export type CoachTab = "chat" | "injury" | "guidance";

export interface InjuryForm {
  bodyPart: string;
  severity: string;
  bonePain: boolean;
  chestPain: boolean;
  note: string;
}

interface CoachChatValue {
  messages: CoachChatMessage[];
  phase: CoachPhase;
  input: string;
  setInput: (text: string) => void;
  activeTab: CoachTab;
  setActiveTab: (tab: CoachTab) => void;
  /** Set when the Athlete opens a citation, so the guidance tab lands on the
   *  passage they asked about rather than the top of the library. */
  guidanceFocus: { bodyPart: string; phase: string } | null;
  openCitation: (citation: Citation) => void;
  injury: InjuryForm;
  setInjury: Dispatch<SetStateAction<InjuryForm>>;
  reportContext: CoachReportContext | null;

  send: (text?: string) => Promise<void>;
  submitTriage: () => void;
  /** Null when applied; otherwise what to tell the Athlete. */
  acceptProposal: (proposal: CoachProposal) => Promise<string | null>;
  shareProposal: (proposal: CoachProposal) => Promise<void>;
  dismissProposal: (proposal: CoachProposal) => void;

  drawerOpen: boolean;
  /** Opens the drawer; a body report is added to the conversation first. */
  openCoach: (reportContext?: CoachReportContext) => void;
  closeCoach: () => void;
}

const CoachChatContext = createContext<CoachChatValue | null>(null);

export function CoachChatProvider({ children }: { children: ReactNode }) {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const { refetchTrainingPlan } = useWorkspace();
  const en = locale === "en";

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<CoachTab>("chat");
  const [guidanceFocus, setGuidanceFocus] = useState<{ bodyPart: string; phase: string } | null>(
    null,
  );
  const [reportContext, setReportContext] = useState<CoachReportContext | null>(null);
  const [injury, setInjury] = useState<InjuryForm>({
    bodyPart: "膝蓋 (Knee)",
    severity: "輕微 (Mild)",
    bonePain: false,
    chestPain: false,
    note: "",
  });
  const [messages, setMessages] = useState<CoachChatMessage[]>(() => [
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

  const token = auth?.accessToken ?? null;
  const sendingRef = useRef(false);

  const send = useCallback(
    async (textToSend?: string) => {
      const text = (textToSend ?? input).trim();
      if (!text || isBusy(phase) || sendingRef.current) return;
      sendingRef.current = true;

      // The previous answer lives in the phase until now; fold it into the
      // transcript so it is not lost, and so the coach can see what it said.
      const priorAnswer = phase.kind === "failed" ? "" : visibleText(phase).trim();
      const transcript: CoachChatMessage[] = priorAnswer
        ? [...messages, { role: "assistant", content: priorAnswer }]
        : messages;
      const historyWithUser: CoachChatMessage[] = [...transcript, { role: "user", content: text }];

      setMessages(historyWithUser);
      setInput("");
      setActiveTab("chat");
      dispatch({ type: "ASKED" });

      const unavailableText = en
        ? "Your coach cannot be reached right now. Your plan and any safety guidance you already have still stand."
        : "目前聯絡不上教練。你既有的課表與安全建議仍然有效；若有持續的急性疼痛，請諮詢專業醫師。";

      if (!token) {
        dispatch({ type: "FAILED", text: unavailableText });
        sendingRef.current = false;
        return;
      }

      let sawText = false;
      try {
        await streamChatWithCoach(
          token,
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
      } finally {
        sendingRef.current = false;
      }
    },
    [en, input, messages, phase, token],
  );

  const acceptProposal = useCallback(
    async (proposal: CoachProposal): Promise<string | null> => {
      if (!token || !proposal.id) return en ? "Sign in again to apply this plan." : "請重新登入後再套用課表。";
      const outcome = await acceptCoachProposal(token, proposal.id);
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
    },
    [en, refetchTrainingPlan, token],
  );

  /** Hands the suggestion to the coach; scheduling stays the coach's call. */
  const shareProposal = useCallback(
    async (proposal: CoachProposal): Promise<void> => {
      if (!token || !proposal.id) throw new Error(en ? "Sign in again to share." : "請重新登入後再分享。");
      await shareCoachProposal(token, proposal.id);
    },
    [en, token],
  );

  const dismissProposal = useCallback(
    (proposal: CoachProposal) => {
      dispatch({ type: "PROPOSAL_DISMISSED" });
      if (token && proposal.id) {
        void dismissCoachProposal(token, proposal.id).catch(() => {
          // Declining is the Athlete's decision either way; a failed record of
          // it must not become their problem.
        });
      }
    },
    [token],
  );

  const submitTriage = useCallback(() => {
    const prompt = `【身體回報】部位：${injury.bodyPart}，嚴重度：${injury.severity}。${
      injury.bonePain ? "（注意：負重時出現局部骨痛）" : ""
    }${injury.chestPain ? "（注意：運動中胸悶或呼吸困難）" : ""}${
      injury.note ? ` 自述症狀：${injury.note}` : ""
    }。請評估我是否還能繼續跑步，並給我處置建議。`;
    void send(prompt);
  }, [injury, send]);

  const openCitation = useCallback((citation: Citation) => {
    setGuidanceFocus({ bodyPart: citation.bodyParts[0] ?? "", phase: citation.phase ?? "" });
    setActiveTab("guidance");
  }, []);

  const openCoach = useCallback(
    (context?: CoachReportContext) => {
      if (context) {
        setReportContext(context);
        setInjury((current) => ({
          ...current,
          bodyPart: context.bodyPart,
          severity: context.severityBand,
        }));
        setMessages((current) =>
          appendOnce(current, { role: "assistant", content: reportContextMessage(context, en) }),
        );
        setActiveTab("chat");
      }
      setDrawerOpen(true);
    },
    [en],
  );

  const closeCoach = useCallback(() => setDrawerOpen(false), []);

  const value = useMemo<CoachChatValue>(
    () => ({
      messages,
      phase,
      input,
      setInput,
      activeTab,
      setActiveTab,
      guidanceFocus,
      openCitation,
      injury,
      setInjury,
      reportContext,
      send,
      submitTriage,
      acceptProposal,
      shareProposal,
      dismissProposal,
      drawerOpen,
      openCoach,
      closeCoach,
    }),
    [
      messages,
      phase,
      input,
      activeTab,
      guidanceFocus,
      openCitation,
      injury,
      reportContext,
      send,
      submitTriage,
      acceptProposal,
      shareProposal,
      dismissProposal,
      drawerOpen,
      openCoach,
      closeCoach,
    ],
  );

  return <CoachChatContext.Provider value={value}>{children}</CoachChatContext.Provider>;
}

export function useCoachChat(): CoachChatValue {
  const value = useContext(CoachChatContext);
  if (!value) throw new Error("useCoachChat must be used inside CoachChatProvider");
  return value;
}
