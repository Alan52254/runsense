/** The API's CoachChatTransport: the signed-in user's token over the
 *  guidance endpoints, and the workspace's own plan refetch. */

import {
  acceptCoachProposal,
  dismissCoachProposal,
  shareCoachProposal,
  streamChatWithCoach,
} from "./apiClient.ts";
import type { CoachChatTransport } from "../lib/coachSession.ts";

export function apiCoachTransport(accessToken: string, refreshPlan: () => Promise<void>): CoachChatTransport {
  return {
    streamMessage: (history, onEvent, onComplete) =>
      streamChatWithCoach(accessToken, history, onEvent, onComplete),
    acceptProposal: (proposalId) => acceptCoachProposal(accessToken, proposalId),
    dismissProposal: (proposalId) => dismissCoachProposal(accessToken, proposalId),
    shareProposal: (proposalId) => shareCoachProposal(accessToken, proposalId),
    refreshPlan,
  };
}
