import { useId } from "react";
import { CoachChatPanel } from "../components/CoachChatPanel.tsx";

/** 健康教練 as a page, in either workspace: the same conversation as the
 *  header drawer, given the whole work area. */
export function CoachChatScreen() {
  const titleId = useId();
  return (
    <div className="cc-page">
      <CoachChatPanel variant="page" titleId={titleId} />
    </div>
  );
}
