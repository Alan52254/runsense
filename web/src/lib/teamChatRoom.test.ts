import assert from "node:assert/strict";
import test from "node:test";
import type { ChatCardWire, ChatMessageWire, ChatRoomWire } from "../data/apiClient.ts";
import { POLL_MS, createTeamChatRoom, layoutMessages } from "./teamChatRoom.ts";
import { inMemoryTeamChatTransport } from "./teamChatTransport.memory.ts";

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

function room(id: string): ChatRoomWire {
  return { id, kind: "direct", team_id: "t", title: id, athlete_id: null, my_role: "athlete", unread: 0, last_message: null, last_at: null };
}

function msg(id: string, at: string, over: Partial<ChatMessageWire> = {}): ChatMessageWire {
  return {
    id, sender_kind: "user", sender_id: "coach", sender_name: "教練", sender_is_coach: true, mine: false,
    body: id, retracted: false, mentions_ai: false, ai_state: null, payload: {}, created_at: at, ...over,
  };
}

function openRoom(transport: ReturnType<typeof inMemoryTeamChatTransport>, atBottom = true) {
  return createTeamChatRoom(transport, { opensFirstRoom: () => true, isAtBottom: () => atBottom });
}

test("an open panel polls rooms and the open room every 3 seconds, and stops when closed", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const transport = inMemoryTeamChatTransport({ rooms: [room("r1")], messages: { r1: [] } });
  const chat = openRoom(transport);

  chat.open();
  await flush();
  await flush();
  const listsAfterOpen = transport.calls.filter((c) => c === "listRooms").length;
  assert.equal(chat.getState().roomId, "r1");

  t.mock.timers.tick(POLL_MS - 1);
  await flush();
  assert.equal(transport.calls.filter((c) => c === "listRooms").length, listsAfterOpen);

  t.mock.timers.tick(1);
  await flush();
  assert.equal(transport.calls.filter((c) => c === "listRooms").length, listsAfterOpen + 1);
  assert.ok(transport.calls.filter((c) => c === "listMessages:r1").length >= 2);

  chat.close();
  const before = transport.calls.length;
  t.mock.timers.tick(POLL_MS * 3);
  await flush();
  assert.equal(transport.calls.length, before);
  assert.equal(POLL_MS, 3000);
});

test("opening a room lands on the first unread message from someone else and marks the room read once", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const transport = inMemoryTeamChatTransport({
    rooms: [room("r1")],
    messages: {
      r1: [
        msg("old", "2026-10-20T08:00:00Z"),
        msg("mine", "2026-10-20T10:00:00Z", { mine: true }),
        msg("new", "2026-10-20T11:00:00Z"),
      ],
    },
    lastReadAt: { r1: "2026-10-20T09:00:00Z" },
  });
  const chat = openRoom(transport);

  chat.open();
  await flush();
  await flush();

  assert.equal(chat.getState().firstUnreadId, "new");
  assert.equal(chat.takePendingScroll(), "unread");
  assert.equal(chat.takePendingScroll(), null);

  t.mock.timers.tick(POLL_MS);
  await flush();
  assert.equal(transport.calls.filter((c) => c === "markRead:r1").length, 1, "no new messages, no second read mark");
});

test("everything read: the room opens at the latest message", async () => {
  const transport = inMemoryTeamChatTransport({
    rooms: [room("r1")],
    messages: { r1: [msg("a", "2026-10-20T08:00:00Z")] },
    lastReadAt: { r1: "2026-10-20T09:00:00Z" },
  });
  const chat = openRoom(transport);

  chat.open();
  await flush();
  await flush();
  chat.close();

  assert.equal(chat.getState().firstUnreadId, null);
  assert.equal(chat.takePendingScroll(), "bottom");
});

test("@助手 is sent as @AI, and the room reloads with the new message", async () => {
  const transport = inMemoryTeamChatTransport({ rooms: [room("r1")], messages: { r1: [] } });
  const chat = openRoom(transport);
  chat.open();
  await flush();
  await flush();
  chat.close();

  const sent = await chat.send("  @助手 明天跑 10K  ");

  assert.equal(sent, true);
  assert.deepEqual(transport.sentBodies, ["@AI 明天跑 10K"]);
  assert.equal(chat.getState().messages.length, 1);
});

test("a failed send keeps the text and says so", async () => {
  const transport = inMemoryTeamChatTransport({ rooms: [room("r1")], messages: { r1: [] }, failSend: true });
  const chat = openRoom(transport);
  chat.open();
  await flush();
  await flush();
  chat.close();

  const sent = await chat.send("哈囉");

  assert.equal(sent, false);
  assert.equal(chat.getState().error, "訊息送出失敗");
  assert.equal(chat.getState().sending, false);
});

test("one sender's messages under 5 minutes apart read as one burst", () => {
  const rows = layoutMessages(
    [
      msg("a", "2026-10-20T12:00:00Z"),
      msg("b", "2026-10-20T12:04:00Z"),
      msg("c", "2026-10-20T12:10:00Z"),
      msg("d", "2026-10-20T12:11:00Z", { sender_id: "athlete", sender_is_coach: false }),
    ],
    [],
    null,
  );

  assert.deepEqual(
    rows.map((r) => [r.message.id, r.newDay, r.first, r.last]),
    [
      ["a", true, true, false],
      ["b", false, false, true],
      ["c", false, true, true],
      ["d", false, true, true],
    ],
  );
});

test("a card under a message, a system line and the unread divider all break a burst", () => {
  const rows = layoutMessages(
    [
      msg("a", "2026-10-20T12:00:00Z"),
      msg("b", "2026-10-20T12:01:00Z"),
      msg("c", "2026-10-20T12:02:00Z"),
      msg("sys", "2026-10-20T12:02:30Z", { sender_kind: "system", sender_id: null }),
      msg("d", "2026-10-20T12:03:00Z"),
    ],
    [{ id: "card", source_message_id: "a" } as never],
    "c",
  );

  assert.deepEqual(
    rows.map((r) => [r.message.id, r.first, r.last, r.attached.length]),
    [
      ["a", true, true, 1],
      ["b", true, true, 0],
      ["c", true, true, 0],
      ["sys", true, true, 0],
      ["d", true, true, 0],
    ],
  );
});

function draftCard(id: string, source: string, dates: string[]): ChatCardWire {
  return {
    id, kind: "plan", status: "pending", source_message_id: source, created_at: "2026-10-23T00:00:00Z",
    payload: { schedule_draft: { week: dates.map((date) => ({ date })) } } as unknown as ChatCardWire["payload"],
  };
}

test("a draft notice whose dates no longer match its draft is marked stale", () => {
  const notice = msg("n1", "2026-10-15T10:00:00Z", {
    sender_kind: "ai", body: "教練正在檢視 10/15–10/21 的整合建議課表，確認後才會排入。", payload: { kind: "schedule_draft_notice" },
  });
  const moved = layoutMessages([notice], [draftCard("c1", "n1", ["2026-10-26", "2026-10-27", "2026-11-01"])], null);
  assert.equal(moved[0]!.staleNotice, true);
  const same = layoutMessages([notice], [draftCard("c1", "n1", ["2026-10-15", "2026-10-18", "2026-10-21"])], null);
  assert.equal(same[0]!.staleNotice, false);
  // no card attached (the athlete's view): the notice is all they have
  assert.equal(layoutMessages([notice], [], null)[0]!.staleNotice, false);
  // an ordinary message is never stale
  assert.equal(layoutMessages([msg("m1", "2026-10-15T10:00:00Z")], [], null)[0]!.staleNotice, false);
});
