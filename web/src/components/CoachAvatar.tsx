import type { CoachAvatarSize } from "../lib/coachChatUi.ts";
import { BrandMark } from "./BrandMark.tsx";

/** The 健康教練's face: BrandMark's runner in a circle with the same hairline
 *  ring as the 台北教練 and 東京選手 avatars. */
export function CoachAvatar({
  size = "md",
  state = "idle",
}: {
  size?: CoachAvatarSize;
  state?: "idle" | "thinking";
}) {
  // COACH_AVATAR_PX (28 / 36 / 64) and the brand steps are the same sizes
  return <BrandMark variant="runner" size={size} state={state} />;
}
