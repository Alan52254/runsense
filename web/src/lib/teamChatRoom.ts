/** The team chat, without React: which rooms there are, which one is open,
 *  what is in it, and keeping all of that fresh.
 *
 *  Polls every 3 s while open. Opening a room finds the first unread message
 *  (like LINE: the view lands there, or on the latest one when everything
 *  was read) and marks the room read whenever new messages arrive. Messages
 *  go out with @助手 normalised to @AI. Nothing here touches the DOM: the
 *  panel says whether the view is at the bottom, and takes the scroll this
 *  module asks for.
 *
 *  It talks to the server only through a TeamChatTransport.
 */

import type { ChatCardWire, ChatMessageWire, ChatRoomWire, PlanCardPayload } from "../data/apiClient.ts";
import { toSendableMention } from "./assistantMention.ts";

export const POLL_MS = 3000;

export interface RoomMessages {
  messages: ChatMessageWire[];
  cards: ChatCardWire[];
  is_coach: boolean;
  /** before this visit; null = never opened */
  last_read_at: string | null;
}

/** What the chat needs from the server, for one signed-in user. */
export interface TeamChatTransport {
  listRooms(): Promise<{ rooms: ChatRoomWire[] }>;
  listMessages(roomId: string): Promise<RoomMessages>;
  markRead(roomId: string): Promise<void>;
  send(roomId: string, body: string): Promise<unknown>;
  draftWeek(roomId: string): Promise<unknown>;
  retractMessage(messageId: string): Promise<unknown>;
  revokeBatch(batchId: string): Promise<unknown>;
  scheduleSuggestion(messageId: string): Promise<unknown>;
  declineSuggestion(messageId: string, reason: string): Promise<unknown>;
  editCard(cardId: string, edit: Record<string, unknown>): Promise<unknown>;
  dismissCard(cardId: string): Promise<unknown>;
  recordDraftReview(cardId: string, reason?: string): Promise<unknown>;
  confirmPlanCard(cardId: string): Promise<unknown>;
  confirmScheduleDraft(cardId: string, choice?: { weather: "update" | "keep"; reason?: string }): Promise<unknown>;
  confirmReportCard(cardId: string): Promise<unknown>;
  /** The server's own wording for a failed call, or null to use ours. */
  describeError(error: unknown): string | null;
}

export type PendingScroll = "unread" | "bottom";

export interface TeamChatState {
  rooms: ChatRoomWire[];
  roomId: string | null;
  messages: ChatMessageWire[];
  cards: ChatCardWire[];
  isCoach: boolean;
  firstUnreadId: string | null;
  sending: boolean;
  drafting: boolean;
  error: string | null;
}

export interface TeamChatRoom {
  getState(): TeamChatState;
  subscribe(listener: () => void): () => void;
  /** The panel opened: a fresh visit to the room it was left on; polling starts. */
  open(): void;
  close(): void;
  /** Opens a room; the room already open is re-entered (lands on unread again). */
  select(roomId: string): void;
  /** Opened from elsewhere (e.g. 團隊課表審核). */
  focus(roomId: string): void;
  reload(): Promise<void>;
  /** True when sent. `onSent` runs as soon as the server has it, before
   *  the reload (the composer clears then). */
  send(body: string, onSent?: () => void): Promise<boolean>;
  draftWeek(): Promise<void>;
  /** A card or message action, then a reload; failures become the error line. */
  act(action: (transport: TeamChatTransport) => Promise<unknown>): Promise<void>;
  setError(error: string | null): void;
  /** The scroll the last load asked for, once. */
  takePendingScroll(): PendingScroll | null;
}

export function firstUnreadMessage(messages: ChatMessageWire[], lastReadAt: string | null): ChatMessageWire | null {
  const lastRead = lastReadAt ? Date.parse(lastReadAt) : null;
  return messages.find((m) => !m.mine && (lastRead === null || Date.parse(m.created_at) > lastRead)) ?? null;
}

/** The helper is still working on one of my messages. */
export function aiThinking(messages: ChatMessageWire[]): boolean {
  return messages.some((m) => m.mine && !m.retracted && m.ai_state === "pending");
}

export function createTeamChatRoom(
  transport: TeamChatTransport,
  options: {
    /** False on a phone: the room list is its own screen, and no room is
     *  opened (and marked read) until it is tapped. */
    opensFirstRoom: () => boolean;
    isAtBottom: () => boolean;
  },
): TeamChatRoom {
  let state: TeamChatState = {
    rooms: [],
    roomId: null,
    messages: [],
    cards: [],
    isCoach: false,
    firstUnreadId: null,
    sending: false,
    drafting: false,
    error: null,
  };
  const listeners = new Set<() => void>();
  // messages seen in this visit to the room; 0 = the next load is a fresh visit
  let lastCount = 0;
  let pendingScroll: PendingScroll | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  const set = (next: Partial<TeamChatState>) => {
    state = { ...state, ...next };
    for (const listener of listeners) listener();
  };
  const describe = (error: unknown, fallback: string) => transport.describeError(error) ?? fallback;

  async function loadRooms() {
    try {
      const r = await transport.listRooms();
      set({ rooms: r.rooms });
      if (state.roomId === null && options.opensFirstRoom() && r.rooms[0]) enter(r.rooms[0].id);
    } catch {
      /* keep the last list */
    }
  }

  async function loadMessages() {
    const roomId = state.roomId;
    if (!roomId) return;
    try {
      const r = await transport.listMessages(roomId);
      if (state.roomId !== roomId) return; // another room was opened meanwhile
      let firstUnreadId = state.firstUnreadId;
      if (lastCount === 0) {
        const first = firstUnreadMessage(r.messages, r.last_read_at);
        firstUnreadId = first?.id ?? null;
        pendingScroll = first ? "unread" : "bottom";
      } else if (r.messages.length !== lastCount) {
        const newest = r.messages[r.messages.length - 1];
        if (options.isAtBottom() || newest?.mine) pendingScroll = "bottom";
      }
      const grew = r.messages.length !== lastCount;
      if (grew) lastCount = r.messages.length;
      set({ messages: r.messages, cards: r.cards, isCoach: r.is_coach, firstUnreadId });
      if (grew) void transport.markRead(roomId).catch(() => {});
    } catch {
      /* transient */
    }
  }

  function enter(roomId: string) {
    lastCount = 0;
    set({ roomId, messages: [], cards: [], firstUnreadId: null });
    void loadMessages();
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
  }

  return {
    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    open() {
      stop();
      void loadRooms();
      lastCount = 0;
      set({ firstUnreadId: null });
      void loadMessages();
      timer = setInterval(() => {
        void loadRooms();
        void loadMessages();
      }, POLL_MS);
    },

    close: stop,

    select(roomId) {
      if (roomId === state.roomId) {
        // reopening the same room (phone: back, then tap again) lands on the
        // unread / latest message again, like a fresh open
        lastCount = 0;
        void loadMessages();
      } else {
        enter(roomId);
      }
    },

    focus(roomId) {
      if (roomId === state.roomId) pendingScroll = "bottom";
      else enter(roomId);
    },

    reload: loadMessages,

    async send(raw, onSent) {
      const body = raw.trim();
      const roomId = state.roomId;
      if (!body || !roomId) return false;
      set({ sending: true, error: null });
      try {
        await transport.send(roomId, toSendableMention(body));
        onSent?.();
        await loadMessages();
        return true;
      } catch (e) {
        set({ error: describe(e, "訊息送出失敗") });
        return false;
      } finally {
        set({ sending: false });
      }
    },

    async draftWeek() {
      const roomId = state.roomId;
      if (!roomId) return;
      set({ drafting: true, error: null });
      try {
        await transport.draftWeek(roomId);
        pendingScroll = "bottom";
        await loadMessages();
      } catch (e) {
        set({ error: describe(e, "建議課表產生失敗") });
      } finally {
        set({ drafting: false });
      }
    },

    async act(action) {
      set({ error: null });
      try {
        await action(transport);
        await loadMessages();
      } catch (e) {
        set({ error: describe(e, "操作失敗") });
      }
    },

    setError: (error) => set({ error }),

    takePendingScroll() {
      const scroll = pendingScroll;
      pendingScroll = null;
      return scroll;
    },
  };
}

/* ---------------- how the messages read on screen ---------------- */

/** Messages from one sender less than 5 min apart read as one burst. */
const GROUP_GAP_MS = 5 * 60 * 1000;

export function dayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function sameBurst(a: ChatMessageWire | undefined, b: ChatMessageWire | undefined): boolean {
  if (!a || !b || a.sender_kind === "system" || b.sender_kind === "system") return false;
  return a.sender_kind === b.sender_kind && a.sender_id === b.sender_id
    && dayKey(a.created_at) === dayKey(b.created_at)
    && Math.abs(Date.parse(b.created_at) - Date.parse(a.created_at)) < GROUP_GAP_MS;
}

export interface MessageLayout {
  message: ChatMessageWire;
  /** the day pill goes above it */
  newDay: boolean;
  /** opens a burst: shows the sender's name */
  first: boolean;
  /** closes a burst: shows the avatar and time */
  last: boolean;
  /** confirmation cards hanging under it */
  attached: ChatCardWire[];
  /** an athlete's 健康教練 suggestion, shown as a card of its own */
  suggestion: boolean;
  /** a 「教練正在檢視 M/D–M/D」 notice whose draft has since moved to other
   *  dates: the card under it says what is under review, the bubble would not */
  staleNotice: boolean;
}

const NOTICE_RANGE = /(\d{1,2})\/(\d{1,2})\s*[–-]\s*(\d{1,2})\/(\d{1,2})/;

function monthDay(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
}

function isStaleNotice(m: ChatMessageWire, attached: ChatCardWire[]): boolean {
  if (m.payload.kind !== "schedule_draft_notice") return false;
  const match = m.body.match(NOTICE_RANGE);
  if (!match) return false;
  const noticeRange = `${Number(match[1])}/${Number(match[2])}–${Number(match[3])}/${Number(match[4])}`;
  return attached.some((c) => {
    if (c.kind !== "plan" || c.status !== "pending") return false;
    const dates = ((c.payload as PlanCardPayload).schedule_draft?.week ?? []).map((w) => w.date).sort();
    if (dates.length === 0) return false;
    return `${monthDay(dates[0]!)}–${monthDay(dates[dates.length - 1]!)}` !== noticeRange;
  });
}

export function layoutMessages(
  messages: ChatMessageWire[],
  cards: ChatCardWire[],
  firstUnreadId: string | null,
): MessageLayout[] {
  const cardsBySource = new Map<string, ChatCardWire[]>();
  for (const c of cards) cardsBySource.set(c.source_message_id, [...(cardsBySource.get(c.source_message_id) ?? []), c]);
  return messages.map((m, i) => {
    const prev = messages[i - 1];
    const next = messages[i + 1];
    const newDay = !prev || dayKey(prev.created_at) !== dayKey(m.created_at);
    const attached = cardsBySource.get(m.id) ?? [];
    const suggestion = m.payload.kind === "coach_suggestion" && !m.retracted;
    // a card under a message ends its burst
    const first = newDay || m.id === firstUnreadId || !sameBurst(prev, m) || (cardsBySource.get(prev.id) ?? []).length > 0;
    const last = !sameBurst(m, next) || next?.id === firstUnreadId || attached.length > 0 || suggestion;
    return { message: m, newDay, first, last, attached, suggestion, staleNotice: isStaleNotice(m, attached) };
  });
}
