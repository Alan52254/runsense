/* The one health-coach conversation.
 *
 * The header drawer and the 健康教練 page (in both workspaces) are frames
 * around the same panel; this provider owns everything they show, so a
 * message sent in one is in the other, and 身體回報 hands its report to the
 * same conversation instead of starting a second one. Mounted above both
 * workspaces' routes so switching 選手／教練 keeps the conversation; it is
 * keyed on the signed-in user, so signing out ends it.
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { CoachChatMessage } from "../data/apiClient.ts";
import { apiCoachTransport } from "../data/coachChatTransport.ts";
import type { Citation, CoachPhase, CoachProposal } from "../lib/coachConversation.ts";
import type { CoachReportContext } from "../lib/coachChatSession.ts";
import { createCoachSession } from "../lib/coachSession.ts";
import type { CoachChatTransport } from "../lib/coachSession.ts";
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
  /** Asks the unanswered question again after a failure. */
  retry: () => Promise<void>;
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
    // nothing is preselected: a report is only sendable once the Athlete
    // has chosen a body part and a severity themselves
    bodyPart: "",
    severity: "",
    bonePain: false,
    chestPain: false,
    note: "",
  });
  const [input, setInput] = useState("");

  // The conversation itself lives in a plain session; this provider only
  // hands it the signed-in user's transport and the current language.
  const token = auth?.accessToken ?? null;
  const transport = useMemo<CoachChatTransport | null>(
    () => (token ? apiCoachTransport(token, refetchTrainingPlan) : null),
    [token, refetchTrainingPlan],
  );
  const transportRef = useRef(transport);
  transportRef.current = transport;
  const enRef = useRef(en);
  enRef.current = en;
  const [session] = useState(() =>
    createCoachSession({
      transport: () => transportRef.current,
      english: () => enRef.current,
      welcome: [
        {
          role: "assistant",
          content: en
            ? "Hello — I am your RunSense coach. Ask me about today's session, how the weather changes your pace, how your recent load is tracking, or anything your body is telling you."
            : "你好，我是你的 RunSense 教練。今天該練什麼、天氣怎麼影響配速、最近的負荷狀況，或身體哪裡不舒服，都可以問我。",
        },
      ],
    }),
  );
  const { messages, phase } = useSyncExternalStore(session.subscribe, session.getState);

  const send = useCallback(
    async (textToSend?: string) => {
      const asked = session.send(textToSend ?? input);
      if (!asked) return;
      setInput("");
      setActiveTab("chat");
      await asked;
    },
    [input, session],
  );

  const retry = useCallback(async () => {
    await session.retry();
  }, [session]);

  const acceptProposal = useCallback((proposal: CoachProposal) => session.acceptProposal(proposal), [session]);
  const shareProposal = useCallback((proposal: CoachProposal) => session.shareProposal(proposal), [session]);
  const dismissProposal = useCallback((proposal: CoachProposal) => session.dismissProposal(proposal), [session]);

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
        session.addReport(context);
      }
      // opened from the header (or with a report): land on 問教練, not on
      // whichever tab was left open last time. A citation opens its passage
      // from inside the panel (openCitation), never through here.
      setActiveTab("chat");
      setDrawerOpen(true);
    },
    [session],
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
      retry,
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
      retry,
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
