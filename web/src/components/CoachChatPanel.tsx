import { useRef } from "react";
import { ArrowDown, X } from "@phosphor-icons/react";
import { usableAcwr } from "../lib/acwr.ts";
import { headerShowsFace, tabDirection } from "../lib/coachChatUi.ts";
import { isBusy } from "../lib/coachConversation.ts";
import { openingPrompts } from "../lib/coachPrompts.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import type { CoachTab } from "../state/CoachChatContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { useWorkspace } from "../state/WorkspaceContext.tsx";
import { CoachAvatar } from "./CoachAvatar.tsx";
import { CoachComposer } from "./CoachComposer.tsx";
import { CoachContextChip } from "./CoachContextChip.tsx";
import { CoachInjuryForm } from "./CoachInjuryForm.tsx";
import { CoachMenu } from "./CoachMenu.tsx";
import { CoachThread } from "./CoachThread.tsx";
import { GuidanceLibrary } from "./GuidanceLibrary.tsx";
import { useStickToEnd } from "./useStickToEnd.ts";

/** The health-coach conversation. The drawer and the 健康教練 page are frames
 *  around this one panel; its state lives in CoachChatProvider, so both show
 *  the same conversation. The panel only composes: header (face, 教練正在看,
 *  menu), the thread or a form, and the composer. */
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
  const busy = isBusy(phase);

  const sentCount = messages.filter((message) => message.role === "user").length;
  const follow = useStickToEnd({
    active: activeTab === "chat",
    sentCount,
    streaming: phase.kind === "streaming",
    version: [messages, phase],
  });

  // the signed-in Athlete's own figures; without enough observation they are left out
  const primaryUnit = trainingLoad.units[0] ?? null;
  const loadRatio = usableAcwr(primaryUnit?.loadRatio)?.toFixed(2) ?? "—";
  const temperatureC =
    liveWeather && liveWeather.state !== "UNAVAILABLE" ? liveWeather.temperature_c : null;
  const humidityPct =
    liveWeather?.humidity_pct !== null && liveWeather?.humidity_pct !== undefined
      ? Math.round(liveWeather.humidity_pct)
      : null;
  const cards = openingPrompts({ en, loadRatio, temperatureC, humidityPct, report: reportContext });

  const tabs: { id: CoachTab; label: string }[] = [
    { id: "chat", label: en ? "Ask" : "問教練" },
    { id: "injury", label: en ? "How you feel" : "身體回報" },
    { id: "guidance", label: en ? "Guidance" : "專業指引" },
  ];

  // the content slides the way you went
  const slideRef = useRef<{ tab: CoachTab; dir: "forward" | "back" | "none" }>({ tab: activeTab, dir: "none" });
  if (slideRef.current.tab !== activeTab) {
    slideRef.current = { tab: activeTab, dir: tabDirection(tabs.map((tab) => tab.id), slideRef.current.tab, activeTab) };
  }

  const title = en ? "Health Coach" : "健康教練";
  const section = tabs.find((tab) => tab.id === activeTab)?.label ?? "";

  return (
    <section
      className={`cc-panel cc-panel--${variant}`}
      aria-labelledby={variant === "page" ? titleId : undefined}
    >
      <header className="cc-head">
        <div className="cc-head-in">
          {headerShowsFace({ tab: activeTab, hasUserMessage: sentCount > 0, phaseKind: phase.kind }) && (
            <CoachAvatar size="md" state={busy ? "thinking" : "idle"} />
          )}
          <div className="cc-head-text">
            {variant === "page" ? (
              <h1 className="page-title is-shell-title cc-title" id={titleId}>
                {title}
              </h1>
            ) : (
              <h2 className="cc-title" id={titleId}>
                {title}
              </h2>
            )}
            {activeTab !== "chat" && <span className="cc-section">{section}</span>}
          </div>
          <CoachContextChip phase={phase} en={en} locale={locale} trainingLoad={trainingLoad} liveWeather={liveWeather} />
          <CoachMenu
            items={tabs}
            active={activeTab}
            onSelect={setActiveTab}
            label={en ? "Switch: Ask, How you feel, Guidance" : "切換：問教練、身體回報、專業指引"}
          />
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
        </div>
      </header>

      <div className="cc-body-wrap">
        <div className="cc-body" data-tab={activeTab} ref={follow.scrollRef} {...follow.bind}>
          <div className="cc-col">
            <div className="cc-slide" key={activeTab} data-dir={slideRef.current.dir}>
              {activeTab === "chat" && <CoachThread en={en} openingCards={cards} />}
              {activeTab === "injury" && <CoachInjuryForm en={en} />}
              {activeTab === "guidance" && (
                <GuidanceLibrary
                  en={en}
                  initialBodyPart={coach.guidanceFocus?.bodyPart || reportContext?.bodyPart}
                  initialPhase={coach.guidanceFocus?.phase}
                />
              )}
            </div>
          </div>
        </div>
        {follow.behind && (
          <button type="button" className="cc-latest" onClick={follow.jump}>
            {en ? "New reply" : "新回覆"}
            <ArrowDown size={14} weight="bold" aria-hidden="true" />
          </button>
        )}
      </div>

      {activeTab === "chat" && (
        <div className="cc-col cc-col--composer">
          <CoachComposer en={en} busy={busy} />
        </div>
      )}
    </section>
  );
}
