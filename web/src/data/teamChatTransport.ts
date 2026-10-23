/** The API's TeamChatTransport: the chat endpoints with one user's token. */

import {
  ApiError,
  confirmPlanCard,
  confirmReportCard,
  confirmScheduleDraft,
  createScheduleDraft,
  declineSuggestion,
  dismissChatCard,
  editChatCard,
  getChatMessages,
  getChatRooms,
  markChatRead,
  recordDraftReview,
  retractChatMessage,
  revokePlanBatch,
  scheduleSuggestion,
  sendChatMessage,
} from "./apiClient.ts";
import type { TeamChatTransport } from "../lib/teamChatRoom.ts";

export function apiTeamChatTransport(accessToken: string): TeamChatTransport {
  return {
    listRooms: () => getChatRooms(accessToken),
    listMessages: (roomId) => getChatMessages(accessToken, roomId),
    markRead: (roomId) => markChatRead(accessToken, roomId),
    send: (roomId, body) => sendChatMessage(accessToken, roomId, body),
    draftWeek: (roomId) => createScheduleDraft(accessToken, roomId),
    retractMessage: (messageId) => retractChatMessage(accessToken, messageId),
    revokeBatch: (batchId) => revokePlanBatch(accessToken, batchId),
    scheduleSuggestion: (messageId) => scheduleSuggestion(accessToken, messageId),
    declineSuggestion: (messageId, reason) => declineSuggestion(accessToken, messageId, reason),
    editCard: (cardId, edit) => editChatCard(accessToken, cardId, edit),
    dismissCard: (cardId) => dismissChatCard(accessToken, cardId),
    recordDraftReview: (cardId, reason) => recordDraftReview(accessToken, cardId, reason),
    confirmPlanCard: (cardId) => confirmPlanCard(accessToken, cardId),
    confirmScheduleDraft: (cardId, choice) => confirmScheduleDraft(accessToken, cardId, choice),
    confirmReportCard: (cardId) => confirmReportCard(accessToken, cardId),
    describeError: (error) => (error instanceof ApiError ? error.message : null),
  };
}
