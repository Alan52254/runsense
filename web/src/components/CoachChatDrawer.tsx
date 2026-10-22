import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { CoachChatPanel } from "./CoachChatPanel.tsx";
import { useCoachChat } from "../state/CoachChatContext.tsx";
import { wrapFocusIndex } from "../lib/coachChatSession.ts";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** The header's health-coach drawer: a frame around the shared panel.
 *  Esc closes it, Tab stays inside while it is open, and focus goes back to
 *  whatever opened it. */
export function CoachChatDrawer() {
  const { drawerOpen, closeCoach } = useCoachChat();
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    const opener = document.activeElement as HTMLElement | null;
    const sheet = sheetRef.current;
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    const previousOverflow = document.body.style.overflow;
    if (root) root.inert = true;
    document.body.style.overflow = "hidden";
    const initialFocus = sheet?.querySelector<HTMLElement>(".cc-input, .cc-close") ?? sheet;
    initialFocus?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCoach();
        return;
      }
      if (event.key !== "Tab" || !sheet) return;
      const focusables = Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((element) => element.getClientRects().length > 0);
      const index = focusables.indexOf(document.activeElement as HTMLElement);
      const target = wrapFocusIndex(focusables.length, index, event.shiftKey);
      if (target !== null) {
        event.preventDefault();
        focusables[target].focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (root) root.inert = wasInert;
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, [drawerOpen, closeCoach]);

  if (!drawerOpen) return null;

  return createPortal(
    <div
      className="cc-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeCoach();
      }}
    >
      <div
        className="cc-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={sheetRef}
      >
        <CoachChatPanel variant="drawer" titleId={titleId} onClose={closeCoach} />
      </div>
    </div>,
    document.body,
  );
}
