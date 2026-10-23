/** An in-memory TeamChatTransport: rooms and messages held in arrays, every
 *  call recorded. For node:test, where there is no server to poll. */

import type { ChatMessageWire, ChatRoomWire } from "../data/apiClient.ts";
import type { TeamChatTransport } from "./teamChatRoom.ts";

export interface InMemoryTeamChatTransport extends TeamChatTransport {
  /** "listRooms", "listMessages:<room>", "markRead:<room>", "send:<room>", ... */
  readonly calls: string[];
  readonly sentBodies: string[];
}

export function inMemoryTeamChatTransport(seed: {
  rooms: ChatRoomWire[];
  messages: Record<string, ChatMessageWire[]>;
  lastReadAt?: Record<string, string>;
  failSend?: boolean;
}): InMemoryTeamChatTransport {
  const calls: string[] = [];
  const sentBodies: string[] = [];
  const messages = Object.fromEntries(Object.entries(seed.messages).map(([id, list]) => [id, [...list]]));
  const record = (call: string) => {
    calls.push(call);
    return Promise.resolve(null);
  };

  return {
    calls,
    sentBodies,
    async listRooms() {
      calls.push("listRooms");
      return { rooms: [...seed.rooms] };
    },
    async listMessages(roomId) {
      calls.push(`listMessages:${roomId}`);
      return { messages: [...(messages[roomId] ?? [])], cards: [], is_coach: false, last_read_at: seed.lastReadAt?.[roomId] ?? null };
    },
    async markRead(roomId) {
      calls.push(`markRead:${roomId}`);
    },
    async send(roomId, body) {
      calls.push(`send:${roomId}`);
      if (seed.failSend) throw new Error("offline");
      sentBodies.push(body);
      (messages[roomId] ??= []).push({
        id: `sent-${sentBodies.length}`, sender_kind: "user", sender_id: "me", sender_name: "我", sender_is_coach: false,
        mine: true, body, retracted: false, mentions_ai: body.startsWith("@AI"), ai_state: null, payload: {},
        created_at: new Date(0).toISOString(),
      });
      return { id: `sent-${sentBodies.length}`, ai_pending: false };
    },
    draftWeek: (roomId) => record(`draftWeek:${roomId}`),
    retractMessage: (id) => record(`retractMessage:${id}`),
    revokeBatch: (id) => record(`revokeBatch:${id}`),
    scheduleSuggestion: (id) => record(`scheduleSuggestion:${id}`),
    declineSuggestion: (id) => record(`declineSuggestion:${id}`),
    editCard: (id) => record(`editCard:${id}`),
    dismissCard: (id) => record(`dismissCard:${id}`),
    recordDraftReview: (id) => record(`recordDraftReview:${id}`),
    confirmPlanCard: (id) => record(`confirmPlanCard:${id}`),
    confirmScheduleDraft: (id) => record(`confirmScheduleDraft:${id}`),
    confirmReportCard: (id) => record(`confirmReportCard:${id}`),
    describeError: () => null,
  };
}
