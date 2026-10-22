import { useId } from "react";
import { CoachChatPanel } from "./CoachChatPanel.tsx";
import { SlideOver } from "./motion.tsx";
import { useCoachChat } from "../state/CoachChatContext.tsx";

/** The header's health-coach drawer: the shared panel in the one SlideOver
 *  frame (Esc, focus trap and focus return live there). */
export function CoachChatDrawer() {
  const { drawerOpen, closeCoach } = useCoachChat();
  const titleId = useId();

  return (
    <SlideOver
      open={drawerOpen}
      onClose={closeCoach}
      labelledBy={titleId}
      initialFocus=".cc-input, .cc-close"
      className="cc-sheet"
    >
      <CoachChatPanel variant="drawer" titleId={titleId} onClose={closeCoach} />
    </SlideOver>
  );
}
