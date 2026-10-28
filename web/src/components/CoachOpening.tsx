import { CloudSun, FirstAidKit, Pulse, Timer } from "@phosphor-icons/react";
import type { CSSProperties } from "react";
import type { OpeningCardText } from "../lib/coachPrompts.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import { CoachAvatar } from "./CoachAvatar.tsx";

const CARD_ICONS = [Pulse, CloudSun, Timer, FirstAidKit];

/** The first screen: the coach's face, its greeting, and four things worth
 *  asking, each saying which of the Athlete's records it draws on. The greeting
 *  is the only sentence. On the first question it folds away over
 *  --motion-slide and the thread grows into the space. */
export function CoachOpening({
  greeting,
  cards,
  collapsed,
  busy,
}: {
  greeting: string;
  cards: OpeningCardText[];
  collapsed: boolean;
  busy: boolean;
}) {
  const coach = useCoachChat();
  return (
    <div className="cc-fold" data-collapsed={collapsed || undefined} inert={collapsed || undefined}>
      <section className="cc-opening">
        <span className="cc-seq" style={{ "--i": 0 } as CSSProperties}>
          <CoachAvatar size="lg" />
        </span>
        <p className="cc-greeting cc-seq" style={{ "--i": 1 } as CSSProperties}>
          {greeting}
        </p>
        <ul className="cc-cards cc-seq" style={{ "--i": 2 } as CSSProperties}>
          {cards.map((card, index) => {
            const Icon = CARD_ICONS[index];
            return (
              <li key={card.prompt}>
                <button type="button" className="cc-card" disabled={busy} onClick={() => void coach.send(card.prompt)}>
                  <Icon size={20} weight="bold" aria-hidden="true" className="cc-card-icon" />
                  <span className="cc-card-text">{card.prompt}</span>
                  <span className="cc-card-src">{card.source}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
