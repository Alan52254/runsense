import type { CSSProperties } from "react";
/* Team chat side panel: the team room, one-to-one rooms, and the @AI
 * helper's confirmation cards (visible to their owner only).
 *
 * Polls every 3 s while open. Nothing the AI prepares is scheduled or
 * filed until its owner confirms the card: the coach for a plan (needs the
 * coach view's MFA, like every other coach write), the athlete for a
 * body-status report. */

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Badge, Button, Notice } from "./ui.tsx";
import type { Tone } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import { SlideOver } from "./motion.tsx";
import { hasAssistantMention, toggleAssistantMention } from "../lib/assistantMention.ts";
import { paceRangeLabel } from "../lib/planLabels.ts";
import { acwrValueText } from "../lib/acwr.ts";
import { ApiError } from "../data/apiClient.ts";
import { apiTeamChatTransport } from "../data/teamChatTransport.ts";
import { aiThinking as helperIsThinking, createTeamChatRoom, dayKey, layoutMessages } from "../lib/teamChatRoom.ts";
import type { TeamChatTransport } from "../lib/teamChatRoom.ts";
import type {
  BodyReportPayload,
  ChatCardWire,
  ChatMessageWire,
  ChatRoomWire,
  DraftWeatherChange,
  PlanBlockWire,
  PlanCardPayload,
  PlanDayWire,
  PlanPreviewItemWire,
  ScheduleDraftWire,
} from "../data/apiClient.ts";
import { Text } from "./Text.tsx";
import { summarizeDraftWeek, type DraftWeekSummary } from "../lib/draftSummary.ts";

const isPhoneLayout = () => typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 720px)").matches;

/** On a phone keyboard Enter must stay a newline: coach plans are multi-line. */
function enterSends(): boolean {
  return !(typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches);
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function weekday(iso: string | null): string {
  if (!iso) return "";
  return "日一二三四五六"[new Date(`${iso}T00:00:00`).getDay()];
}

function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 今天 / 昨天 / 10/8（週三） -- the pill between days */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (dayKey(iso) === dayKey(today.toISOString())) return "今天";
  if (dayKey(iso) === dayKey(yesterday.toISOString())) return "昨天";
  return `${d.getMonth() + 1}/${d.getDate()}（週${"日一二三四五六"[d.getDay()]}）`;
}

/** room list: time today, otherwise the date */
function roomTime(iso: string | null): string {
  if (!iso) return "";
  if (dayKey(iso) === dayKey(new Date().toISOString())) return hhmm(iso);
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

type AvatarKind = "coach" | "athlete" | "ai" | "team";

/** Athlete avatars get a stable tint from their name. */
function tintOf(name: string): number {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)!) % 360;
  return h;
}

const SKIN = ["var(--avatar-skin-light)", "var(--avatar-skin-medium)", "var(--avatar-skin-deep)"];
const HAIR = ["var(--avatar-hair-dark)", "var(--avatar-hair-brown)", "var(--avatar-hair-black)"];

/** Drawn portraits, like a sports app's default avatars: the coach in a cap
 *  with a whistle, an athlete in a singlet wearing a race bib with their
 *  initial, the team as a track. The helper wears the RunSense mark, the
 *  way an official account does. */
export function ChatAvatar({ kind, name, size = 36 }: { kind: AvatarKind; name: string; size?: number }) {
  const tint = tintOf(name);
  const initial = [...name][0] ?? "?";
  const skin = SKIN[tint % 3];
  if (kind === "ai") {
    return (
      <span className="chat-avatar is-ai" style={{ "--avatar-size": `${size}px` } as CSSProperties} aria-hidden="true">
        <Icon name="runner" size={Math.round(size * 0.56)} weight="bold" />
      </span>
    );
  }
  return (
    <span className={`chat-avatar is-${kind}`} style={{ "--avatar-size": `${size}px` } as CSSProperties} aria-hidden="true">
      <svg viewBox="0 0 40 40" width={size} height={size}>
        {kind === "team" ? (
          <>
            <rect width="40" height="40" fill="var(--avatar-uniform)" />
            <rect x="5.5" y="11" width="29" height="18" rx="9" fill="var(--avatar-track)" />
            <rect x="10" y="15" width="20" height="10" rx="5" fill="var(--avatar-field)" />
            <rect x="5.5" y="11" width="29" height="18" rx="9" fill="none" stroke="var(--illustration-white)" strokeOpacity=".55" strokeWidth=".6" strokeDasharray="1.6 1.4" />
            <text x="20" y="23" textAnchor="middle" fontSize="8" fontWeight="800" fill="var(--illustration-white)">{initial}</text>
          </>
        ) : kind === "coach" ? (
          <>
            <rect width="40" height="40" fill="var(--avatar-sky)" />
            <g transform="translate(-3 -3) scale(1.15)">
            <path d="M5 40c0-8.5 6.7-13 15-13s15 4.5 15 13z" fill="var(--avatar-uniform)" />
            <path d="M16.5 27.4 20 31l3.5-3.6" fill="none" stroke="var(--illustration-white)" strokeWidth="1.2" strokeLinejoin="round" />
            <rect x="17.2" y="20.5" width="5.6" height="7" rx="2.4" fill={skin} />
            <circle cx="20" cy="16.5" r="6.6" fill={skin} />
            <path d="M15 28.2 20 36l5-7.8" fill="none" stroke="var(--avatar-trim)" strokeWidth="1.1" />
            <rect x="18" y="34.6" width="5.4" height="3" rx="1.4" fill="var(--avatar-metal)" stroke="var(--avatar-metal-edge)" strokeWidth=".5" />
            <path d="M13.2 15.6a6.8 6.8 0 0 1 13.6 0z" fill="var(--avatar-uniform)" />
            <path d="M12.4 15.1h15.2c1.3 0 1.3 2 0 2H12.4c-1.3 0-1.3-2 0-2z" fill="var(--avatar-trim)" />
            <circle cx="20" cy="9.4" r=".9" fill="var(--avatar-trim)" />
            </g>
          </>
        ) : (
          <>
            <rect width="40" height="40" fill={`hsl(${tint} 55% 88%)`} />
            <g transform="translate(-3 -3) scale(1.15)">
            <path d="M5 40c0-8.5 6.7-13 15-13s15 4.5 15 13z" fill={skin} />
            <path d="M10.8 40v-9.6c2.6-1.9 5.7-2.8 9.2-2.8s6.6.9 9.2 2.8V40z" fill={`hsl(${tint} 55% 42%)`} />
            <path d="M16.2 27.8c1 2 2.3 3 3.8 3s2.8-1 3.8-3z" fill={skin} />
            <rect x="17.2" y="20.5" width="5.6" height="7" rx="2.4" fill={skin} />
            <circle cx="20" cy="16.5" r="6.6" fill={skin} />
            <path d="M13.3 16.2a6.7 6.7 0 0 1 13.4 0c-1.8-2.2-4.2-3.3-6.7-3.3s-4.9 1.1-6.7 3.3z" fill={HAIR[tint % 3]} />
            <rect x="13.3" y="13.9" width="13.4" height="1.7" rx=".85" fill={`hsl(${tint} 55% 42%)`} />
            <rect x="14.2" y="29.8" width="11.6" height="6.8" rx="1" fill="var(--illustration-white)" />
            <circle cx="15.3" cy="30.9" r=".45" fill="var(--avatar-pin)" />
            <circle cx="24.7" cy="30.9" r=".45" fill="var(--avatar-pin)" />
            <text x="20" y="35.4" textAnchor="middle" fontSize="5.4" fontWeight="800" fill="var(--avatar-label)">{initial}</text>
            </g>
          </>
        )}
      </svg>
    </span>
  );
}

function senderAvatarKind(m: ChatMessageWire): AvatarKind {
  return m.sender_kind === "ai" ? "ai" : m.sender_is_coach ? "coach" : "athlete";
}

const COACH_ROLES = new Set(["coach", "head_coach", "owner"]);

/** Who is on the other side of a room, for its avatar. */
function roomAvatarKind(r: ChatRoomWire): AvatarKind {
  if (r.kind === "team") return "team";
  return COACH_ROLES.has(r.my_role) ? "athlete" : "coach";
}

export function TeamChatPanel({ open, onClose, accessToken, onAssignmentsChanged, focusRoom }: {
  open: boolean; onClose: () => void; accessToken: string;
  /** open on this room (e.g. from 團隊課表審核); `at` makes a repeat request count */
  focusRoom?: { roomId: string; at: number } | null;
  /** a plan was confirmed or revoked here: assignments changed */
  onAssignmentsChanged?: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const chat = useMemo(() => {
    const transport = apiTeamChatTransport(accessToken);
    return {
      transport,
      room: createTeamChatRoom(transport, {
        opensFirstRoom: () => !isPhoneLayout(),
        isAtBottom: () => {
          const el = scrollRef.current;
          return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        },
      }),
    };
  }, [accessToken]);
  const { transport } = chat;
  const { rooms, roomId, messages, cards, isCoach, firstUnreadId, sending, drafting, error } =
    useSyncExternalStore(chat.room.subscribe, chat.room.getState);
  const [input, setInput] = useState("");
  // phone layout only: the room list and the open room are separate screens
  const [phoneView, setPhoneView] = useState<"rooms" | "room">("rooms");
  const unreadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // the composer grows with what is typed, up to ~6 lines, then scrolls
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input, open]);

  useEffect(() => {
    if (!focusRoom) return;
    chat.room.focus(focusRoom.roomId);
    setPhoneView("room");
  }, [focusRoom, chat]);

  useEffect(() => {
    if (!open) return;
    chat.room.open();
    return () => chat.room.close();
  }, [open, chat]);

  // Like LINE: opening a room lands on the first unread message (marked by a
  // divider), or on the latest one when everything was read. Afterwards new
  // messages only scroll the view if you were already at the bottom.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || messages.length === 0) return;
    const scroll = chat.room.takePendingScroll();
    if (!scroll) return;
    if (scroll === "unread" && unreadRef.current) {
      el.scrollTop = Math.max(0, unreadRef.current.offsetTop - el.offsetTop - 8);
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, cards, chat]);

  const send = () => chat.room.send(input, () => setInput(""));
  const draftWeek = () => chat.room.draftWeek();
  const act = (fn: (t: TeamChatTransport) => Promise<unknown>) => chat.room.act(fn);
  const reload = () => void chat.room.reload();
  const setError = chat.room.setError;

  const titleId = useId();
  const room = rooms.find((r) => r.id === roomId);
  const aiOn = hasAssistantMention(input);
  const aiThinking = helperIsThinking(messages);

  return (
    <SlideOver open={open} onClose={onClose} size="xl" labelledBy={titleId} className="chat-slide-over">
      <div className="chat-panel" data-phone-view={phoneView}>
        <div className="chat-rooms">
          <div className="chat-rooms-head">
            <h2 id={titleId}>聊天室</h2>
            <button type="button" className="chat-icon-btn" onClick={onClose} aria-label="關閉"><Icon name="x" size={18} /></button>
          </div>
          <div className="chat-room-list">
            {rooms.map((r) => (
              <button key={r.id} type="button" className={`chat-room-item${r.id === roomId ? " is-active" : ""}${r.unread > 0 ? " has-unread" : ""}`} onClick={() => {
                // reopening the same room (phone: back, then tap again) lands
                // on the unread / latest message again, like a fresh open
                chat.room.select(r.id);
                setPhoneView("room");
              }}>
                <ChatAvatar kind={roomAvatarKind(r)} name={r.title} size={46} />
                <span className="chat-room-text">
                  <span className="chat-room-line">
                    <span className="chat-room-title">{r.title}</span>
                    <span className="chat-room-time">{roomTime(r.last_at)}</span>
                  </span>
                  <span className="chat-room-line">
                    <span className="chat-room-last">{r.last_message ?? "還沒有訊息"}</span>
                    {r.unread > 0 && <span className="chat-unread">{r.unread > 99 ? "99+" : r.unread}</span>}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="chat-main">
          <header className="chat-main-head">
            <button type="button" className="chat-icon-btn chat-phone-only" onClick={() => setPhoneView("rooms")} aria-label="返回聊天室列表">
              <Icon name="chevron-left" size={20} />
            </button>
            {room && <ChatAvatar kind={roomAvatarKind(room)} name={room.title} size={40} />}
            <div className="chat-main-title">
              <strong>{room?.title ?? "聊天室"}</strong>
              <span>{room?.kind === "team" ? "全隊都看得到" : "只有你們兩位看得到"}・輸入 @助手 可請助手{isCoach ? "整理課表" : "記錄身體回報"}</span>
            </div>
            {isCoach && room?.kind === "direct" && (
              <button type="button" className="chat-draft-btn" disabled={drafting} onClick={() => void draftWeek()}
                aria-label="整合建議課表"
                title="把負荷、傷痛、天氣、健康教練對話與課表分析整合成一週建議，確認前不會排給選手">
                <Icon name="assignment" size={16} />
                <span>{drafting ? "整理中…" : "整合建議課表"}</span>
              </button>
            )}
            <button type="button" className="chat-icon-btn chat-phone-only chat-main-close" onClick={onClose} aria-label="關閉"><Icon name="x" size={18} /></button>
          </header>
          <div className="chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="chat-empty">
                {room && <ChatAvatar kind={roomAvatarKind(room)} name={room.title} size={64} />}
                <strong>{room ? `跟${room.kind === "team" ? "全隊" : room.title}打聲招呼` : "選一個聊天室"}</strong>
                <span>{isCoach ? "傳訓練提醒，或輸入 @助手 加上課表，讓助手整理成排課確認卡。" : "回報練跑感受，或輸入 @助手 描述哪裡不舒服，讓助手幫你整理成回報。"}</span>
              </div>
            )}
            {layoutMessages(messages, cards, firstUnreadId).map(({ message: m, newDay, first, last, attached, suggestion, staleNotice }) => {
              return (
                <div key={m.id} className="chat-row">
                  {newDay && <div className="chat-day"><span>{dayLabel(m.created_at)}</span></div>}
                  {m.id === firstUnreadId && (
                    <div className="chat-unread-divider" ref={unreadRef}><span><Icon name="finish" size={14} weight="bold" />從這裡開始未讀</span></div>
                  )}
                  {!staleNotice && (
                    <MessageRow m={m} isCoach={isCoach} first={first} last={last}
                      onRetract={() => act((t) => t.retractMessage(m.id))}
                      onRevoke={(b) => act(async (t) => { await t.revokeBatch(b); onAssignmentsChanged?.(); })} />
                  )}
                  {suggestion && (
                    <div className={`chat-attach${m.mine ? " is-mine" : ""}`}>
                      <SuggestionCard m={m} isCoach={isCoach}
                        planOpen={attached.some((c) => c.kind === "plan" && c.status === "pending")}
                        onSchedule={() => act((t) => t.scheduleSuggestion(m.id))}
                        onDecline={(reason) => act((t) => t.declineSuggestion(m.id, reason))} />
                    </div>
                  )}
                  {attached.length > 0 && (
                    <div className="chat-attach">
                      {attached.map((c) =>
                        c.kind === "plan" ? (
                          <PlanCard key={c.id} card={c} transport={transport} onChanged={reload} onConfirmed={onAssignmentsChanged} onError={setError} />
                        ) : (
                          <BodyReportCard key={c.id} card={c} transport={transport} onChanged={reload} onError={setError} />
                        ),
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {aiThinking && (
              <div className="chat-msg is-ai is-first is-last" role="status">
                <ChatAvatar kind="ai" name="RunSense" size={32} />
                <div className="chat-msg-body">
                  <div className="chat-msg-name">RunSense 團隊助手<span className="chat-role is-bot">助手</span></div>
                  <div className="chat-bubble chat-typing" aria-label="助手正在整理"><i /><i /><i /></div>
                </div>
              </div>
            )}
          </div>
          {error && <div className="chat-error"><Notice tone="critical" icon="alert">{error}</Notice></div>}
          {aiOn && (
            <div className="chat-ai-disclosure">
              @助手 會把這段對話送到雲端 AI 模型整理；名字會換成「教練／選手A」，不會傳送 Email 或帳號。
            </div>
          )}
          <div className="chat-input">
            <div className={`chat-composer${aiOn ? " is-ai" : ""}`}>
              <button type="button" className="chat-ai-toggle" aria-pressed={aiOn}
                title={aiOn ? "取消呼叫助手" : "呼叫 RunSense 團隊助手"}
                onClick={() => {
                  setInput((v) => toggleAssistantMention(v));
                  inputRef.current?.focus();
                }}>
                <Icon name="at" size={16} weight="bold" /><span>助手</span>
              </button>
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                aria-label="訊息"
                placeholder={isCoach ? "傳訊息，或 @助手 貼上課表…" : "傳訊息，或 @助手 送出身體回報…"}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && enterSends()) { e.preventDefault(); void send(); } }}
              />
            </div>
            <button type="button" className="chat-send" disabled={sending || !input.trim()} onClick={() => void send()} aria-label="送出">
              <Icon name="send" size={20} weight="fill" />
            </button>
          </div>
        </div>
      </div>
    </SlideOver>
  );
}

function MessageRow({ m, isCoach, first, last, onRetract, onRevoke }: {
  m: ChatMessageWire; isCoach: boolean; first: boolean; last: boolean;
  onRetract: () => void; onRevoke: (batchId: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  if (m.sender_kind === "system") {
    const canRevoke = isCoach && m.payload.kind === "plan_scheduled" && m.payload.batch_id && !m.payload.revoked;
    return (
      <div className="chat-system">
        <Icon name="calendar" size={15} weight="bold" />
        <span>{m.body}</span>
        {m.payload.revoked && <Badge>已撤銷</Badge>}
        {canRevoke && (confirming ? (
          <>
            <Button size="sm" variant="danger" onClick={() => { setConfirming(false); onRevoke(m.payload.batch_id!); }}>確定撤銷</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>取消</Button>
          </>
        ) : <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>撤銷</Button>)}
      </div>
    );
  }
  const ai = m.sender_kind === "ai";
  const name = ai ? "RunSense 團隊助手" : m.sender_name;
  const canRetract = m.mine && !m.retracted;
  return (
    <div className={`chat-msg${m.mine ? " is-mine" : ""}${ai ? " is-ai" : ""}${first ? " is-first" : ""}${last ? " is-last" : ""}`}>
      {!m.mine && (last ? <ChatAvatar kind={senderAvatarKind(m)} name={name} size={32} /> : <span className="chat-avatar-gap" />)}
      <div className="chat-msg-body">
        {!m.mine && first && (
          <div className="chat-msg-name">
            {name}
            {m.sender_is_coach && !ai && <span className="chat-role">教練</span>}
            {ai && <span className="chat-role is-bot">助手</span>}
          </div>
        )}
        <div className="chat-bubble-line">
          <div className={`chat-bubble${m.retracted ? " is-retracted" : ""}`}>
            {m.retracted ? "訊息已收回" : <span className="chat-msg-text">{m.body}</span>}
          </div>
          {canRetract && !confirming && (
            <button type="button" className="chat-msg-more" onClick={() => setConfirming(true)}>收回</button>
          )}
        </div>
        {canRetract && confirming && (
          <div className="chat-msg-actions">
            <Button size="sm" variant="danger" onClick={() => { setConfirming(false); onRetract(); }}>確定收回</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>取消</Button>
          </div>
        )}
        {last && <time className="chat-time" dateTime={m.created_at} title={timeLabel(m.created_at)}>{hhmm(m.created_at)}</time>}
      </div>
    </div>
  );
}

/* ---------------- coach suggestion (backend/app/coach_handoff.py) ---------------- */

const WORKOUT_LABEL: Record<string, string> = {
  REST_AND_SEEK_CARE: "休息並尋求評估",
  REST_DAY: "休息日",
  RECOVERY_RUN: "恢復跑",
  EASY_RUN: "輕鬆跑",
  STEADY_RUN: "穩定跑",
};

/** An AI 健康教練 suggestion the athlete sent. Both sides see it; only the
 *  coach can turn it into a plan card -- which is then checked and confirmed
 *  like any plan. Sending it scheduled nothing. */
/** What the coach did with a suggestion, as both sides see it. */
const DECISION_LABEL: Record<string, { text: string; tone: Tone }> = {
  adopted: { text: "教練已採用", tone: "good" },
  adopted_modified: { text: "教練修改後採用", tone: "good" },
  declined: { text: "教練已婉拒", tone: "neutral" },
};

function SuggestionCard({ m, isCoach, planOpen, onSchedule, onDecline }: {
  m: ChatMessageWire; isCoach: boolean; planOpen: boolean; onSchedule: () => void;
  onDecline: (reason: string) => Promise<unknown>;
}) {
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const c = m.payload.candidate;
  if (!c || !m.payload.date) return null;
  const runs = c.running_allowed && c.duration_minutes > 0;
  const [, month, day] = m.payload.date.split("-").map(Number);
  const decision = m.payload.revoked
    ? { text: "教練排入後已撤銷", tone: "neutral" as Tone }
    : DECISION_LABEL[m.payload.decision ?? ""];
  return (
    <div className={`chat-card${m.mine ? " is-mine" : ""}`}>
      <div className="chat-card-head">
        <Icon name="coach-note" size={14} />
        <strong>AI 健康教練建議 · {month}/{day}（{weekday(m.payload.date)}）</strong>
        <Badge tone={decision?.tone ?? "warning"}>{decision?.text ?? "待教練回覆"}</Badge>
      </div>
      <div>
        {WORKOUT_LABEL[c.workout_type] ?? c.workout_type}
        {runs && ` ${c.duration_minutes} 分鐘`}
        {runs && c.distance_km > 0 && ` · ${c.distance_km} km`}
        {runs && c.pace_range_s_per_km && ` · 配速 ${paceRangeLabel(c.pace_range_s_per_km)}`}
        {m.payload.label && <Text variant="caption">（{m.payload.label}）</Text>}
      </div>
      {(m.payload.coach_assigned ?? []).length > 0 && (
        <Text variant="caption" as="div">這天原本的課表：{m.payload.coach_assigned!.join("、")}</Text>
      )}
      {m.payload.decision === "declined" && m.payload.reason && (
        <Text variant="caption" as="div">教練的理由：{m.payload.reason}</Text>
      )}
      {m.payload.decision ? null : isCoach ? (
        declining ? (
          <div className="chat-msg-actions">
            <input className="input" value={reason} maxLength={300} autoFocus
              placeholder="婉拒的理由（選手和 AI 健康教練都會看到）"
              onChange={(e) => setReason(e.target.value)} />
            <Button size="sm" variant="primary" disabled={!reason.trim()}
              onClick={async () => { await onDecline(reason.trim()); setDeclining(false); }}>送出婉拒</Button>
            <Button size="sm" variant="ghost" onClick={() => setDeclining(false)}>取消</Button>
          </div>
        ) : (
          <div className="chat-msg-actions">
            {runs && !planOpen && <Button size="sm" variant="primary" onClick={onSchedule}>依此排課</Button>}
            <Button size="sm" variant="ghost" onClick={() => setDeclining(true)}>婉拒</Button>
            <span className="field-hint">
              {planOpen ? "已建立排課確認卡，請在下方確認。"
                : runs ? "依此排課會先產生確認卡，確認後才會排入"
                  : "這是休息建議；要調整這天的課表，可以直接 @助手 排課。"}
            </span>
          </div>
        )
      ) : (
        <Text variant="caption" as="div">由教練決定要不要排進課表。</Text>
      )}
    </div>
  );
}

/* ---------------- plan card ---------------- */

const STATUS_LABEL: Record<string, { text: string; tone: Tone }> = {
  new: { text: "新增", tone: "good" },
  overwrite: { text: "覆蓋舊課表", tone: "warning" },
  skip_completed: { text: "已完成，略過", tone: "neutral" },
  need_date: { text: "缺日期", tone: "critical" },
};

/* ---- exact read-out of what will be scheduled (no rounding of the plan) ---- */

function mmss(totalS: number): string {
  const s = Math.round(totalS * 10) / 10;
  const m = Math.floor(s / 60);
  const r = Math.round((s - m * 60) * 10) / 10;
  const rs = Number.isInteger(r) ? String(r).padStart(2, "0") : r.toFixed(1).padStart(4, "0");
  return `${m}:${rs}`;
}

function restText(s: number): string {
  return s < 60 ? `${s} 秒` : mmss(s);
}

function distText(m: number): string {
  return m >= 5000 ? `${m / 1000} km` : `${m} m`;
}

/** "3:30 /km（每趟 3:30）" -- per-rep time from the prescribed pace */
function targetText(b: PlanBlockWire): string {
  if (!b.target_s_per_km) return "未指定配速";
  const pace = `${mmss(b.target_s_per_km)} /km`;
  const per = b.distance_m ? (b.distance_m / 1000) * b.target_s_per_km : null;
  const perText = per === null ? "" : per < 120 ? `${Math.round(per * 10) / 10} 秒` : mmss(per);
  if (b.target_mode === "max") return `${pace} 以內${perText ? `（每趟 ${perText} 內）` : ""}`;
  return `${pace}${perText && b.reps > 1 ? `（每趟 ${perText}）` : ""}`;
}

function PlanStructure({ item }: { item: PlanPreviewItemWire }) {
  const rec = item.record;
  if (item.missing_variant || !rec) {
    return <div className="chat-plan-item"><strong>{item.title}</strong><span className="dev-slow">　這位選手的性別沒有對應的課表，不會排入</span></div>;
  }
  if (!rec.tracked) {
    return (
      <div className="chat-plan-item">
        <div><strong>{rec.title}</strong><Text variant="caption">　{rec.intensity_label}・不追蹤完成</Text></div>
        {rec.notes && <pre className="chat-plan-source">{rec.notes}</pre>}
      </div>
    );
  }
  const blocks = item.blocks ?? [];
  const totalM = blocks.reduce((t, b) => t + (b.distance_m ?? 0) * b.reps, 0);
  return (
    <div className="chat-plan-item">
      <div><strong>{rec.title}</strong><Text variant="caption">　{rec.intensity_label}・約 {rec.duration_minutes} 分鐘{totalM > 0 ? `・主課表 ${totalM >= 1000 ? `${totalM / 1000} km` : `${totalM} m`}` : ""}</Text></div>
      {rec.notes && <Text variant="caption" as="div">選手會看到：{rec.notes}</Text>}
      <ol className="chat-plan-structure">
        {blocks.map((b, i) => (
          <li key={i}><div className="chat-plan-li">
            <span className="chat-plan-work">
              {b.distance_m ? distText(b.distance_m) : `${(b.duration_s ?? 0) / 60} 分鐘`}{b.reps > 1 ? ` × ${b.reps}` : ""}
            </span>
            <span>＠ {targetText(b)}</span>
            {b.rest_s ? <Text variant="caption">趟休 {restText(b.rest_s)}</Text> : null}
            {b.target_text && <Text variant="caption">原寫法：{b.target_text}</Text>}
            {b.rest_after_s && i + 1 < blocks.length ? <div className="chat-plan-setrest">組間休息 {restText(b.rest_after_s)}</div> : null}
          </div></li>
        ))}
      </ol>
    </div>
  );
}

function blockLine(b: PlanBlockWire): string {
  const unit = b.distance_m ? `${b.distance_m}m` : `${(b.duration_s ?? 0) / 60} 分鐘`;
  let s = b.reps > 1 ? `${b.reps} × ${unit}` : unit;
  if (b.target_text) s += ` @ ${b.target_text}`;
  if (b.rest_s) s += `（趟休 ${b.rest_s} 秒）`;
  if (b.rest_after_s) s += `，組休 ${b.rest_after_s / 60} 分`;
  return s;
}

function PlanCard({ card, transport, onChanged, onConfirmed, onError }: {
  card: ChatCardWire; transport: TeamChatTransport; onChanged: () => void; onConfirmed?: () => void; onError: (e: string | null) => void;
}) {
  const p = card.payload as PlanCardPayload;
  const [busy, setBusy] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  // schedule draft only: a moved forecast to decide on, a day being added, a reason
  const [weatherChanges, setWeatherChanges] = useState<DraftWeatherChange[] | null>(null);
  const [reason, setReason] = useState("");
  const [addingDate, setAddingDate] = useState<string | null>(null);
  // once confirmed the card goes away: the "已排入…" system message (with
  // the revoke button) is the record of what was scheduled
  if (card.status === "confirmed") return null;
  if (card.status !== "pending") {
    return null; // cancelled or dismissed: no trace in the chat
  }
  const save = async (edit: Record<string, unknown>) => {
    setBusy(true);
    onError(null);
    try {
      await transport.editCard(card.id, edit);
      onChanged();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "卡片更新失敗");
    } finally {
      setBusy(false);
    }
  };
  const saveDay = (day: PlanDayWire) => save({ days: [day] });
  const previewRows = new Map((card.preview?.rows ?? []).map((r) => [r.key, r]));
  const blocking = p.plan.days.some((d) => !d.removed && (!d.date || (!d.edited && d.problems.length > 0)));

  const draft = p.schedule_draft;
  const summary = draft ? summarizeDraftWeek(p, card.preview) : null;
  return (
    <div className={`chat-card${draft ? " is-draft" : ""}`}>
      <div className="chat-card-head">
        <Icon name="assignment" size={16} />
        <strong>{draft ? `${draft.review_only ? "回溯審核" : "整合建議課表"}（第 ${draft.version} 版）` : "排課確認卡"}</strong>
        <Text variant="caption">{draft?.review_only ? "只有你看得到・只記錄審核結果，不會排入" : "只有你看得到・確認前不會排入"}</Text>
      </div>
      {draft?.stale && draft.stale.length > 0 && (
        <Notice tone="critical" icon="alert" title="草案已失效，請重新產生">
          建立草案後這些資料有變動：{draft.stale.map((x) => x.text).join("；")}
        </Notice>
      )}
      {summary && <DraftWeekHead summary={summary} />}
      {draft && (
        <details className="draft-why">
          <summary>每天的判斷依據與參考資料</summary>
          <DraftOverview draft={draft} addedDates={new Set(p.plan.days.filter((d) => d.coach_added && !d.removed).map((d) => d.date ?? ""))}
            onAdd={draft.stale?.length ? undefined : (date) => setAddingDate(date)} />
        </details>
      )}
      {draft && addingDate && (
        <AddDayForm date={addingDate} busy={busy} onCancel={() => setAddingDate(null)}
          onSave={(day) => { setAddingDate(null); void saveDay(day); }} />
      )}
      {draft && p.plan.days.length === 0 && (
        <Text variant="caption" as="div">這一週沒有需要新增或調整的天數；上方是每天的判斷依據。</Text>
      )}
      <div className="chat-card-athletes">
        <Text variant="caption">套用給：</Text>
        {p.athletes.map((a) => (
          <label key={a.id} className="chat-check">
            <input type="checkbox" checked={a.selected} disabled={busy}
              onChange={(e) => void save({ athletes: p.athletes.map((x) => ({ id: x.id, selected: x.id === a.id ? e.target.checked : x.selected })) })} />
            {a.name}{(a.sex === "male" || a.sex === "female") && <Text variant="caption">（{a.sex === "male" ? "男" : "女"}）</Text>}
          </label>
        ))}
      </div>
      {summary ? (
        <ol className="draft-lines">
          {p.plan.days.map((d, index) => {
            const line = summary.days[index];
            const row = previewRows.get(d.key);
            return (
              <li key={d.key} className={`draft-line${d.removed ? " is-removed" : ""}`}>
                <div className="draft-line-main">
                  <span className="draft-line-date">{line.dateLabel}</span>
                  <span className="draft-line-type">{line.type}</span>
                  {line.distancePace && <span className="draft-line-figure">{line.distancePace}</span>}
                  {line.slot && <span className="draft-line-slot">{line.slot}</span>}
                  <span className="chat-spacer" />
                  <DayControls removed={d.removed} label={line.dateLabel} busy={busy} editing={editingKey === d.key}
                    onToggleEdit={() => setEditingKey(editingKey === d.key ? null : d.key)}
                    onSetRemoved={(removed) => void saveDay({ ...d, removed })} />
                </div>
                {!d.removed && d.problems.length > 0 && !d.edited && <Notice tone="critical" icon="alert">{d.problems.join("；")}（修改或刪除這一天後才能確認）</Notice>}
                {!d.removed && (editingKey === d.key ? (
                  <DayEditor day={d} busy={busy} onSave={(day) => void saveDay(day)} />
                ) : (
                  <details className="draft-line-details">
                    <summary>詳細：選手會看到、原寫法</summary>
                    <div className="draft-line-body">
                      <div className="chat-plan-day-head">
                        <input type="date" className="input input-sm" value={d.date ?? ""} disabled={busy}
                          aria-label="這一天的日期"
                          onChange={(e) => void saveDay({ ...d, date: e.target.value || null })} />
                        <Text variant="caption">週{weekday(d.date)}{d.date_hint ? `・原文：${d.date_hint}` : ""}</Text>
                      </div>
                      <pre className="chat-plan-source">{d.source}</pre>
                      {row?.entries.map((e) => (
                        <div key={e.athlete_id} className="chat-plan-athlete">
                          <div className="chat-plan-entry">
                            <span className="chat-plan-name">{e.name}</span>
                            <Badge tone={STATUS_LABEL[e.status].tone}>{STATUS_LABEL[e.status].text}</Badge>
                          </div>
                          {e.projected_load ? (
                            <div className="field-hint">
                              ACWR 負荷比 {acwrValueText(e.projected_load.before, "zh-TW")} → 排入後 {e.projected_load.on.slice(5).replace("-", "/")}{" "}
                              {acwrValueText(e.projected_load.after, "zh-TW")}（以課表類型預估 RPE）
                            </div>
                          ) : e.load_consent === false ? (
                            <Text variant="caption" as="div">選手未授權查看訓練負荷</Text>
                          ) : null}
                          {e.status !== "skip_completed" && e.items.map((it, k) => <PlanStructure key={k} item={it} />)}
                        </div>
                      ))}
                    </div>
                  </details>
                ))}
              </li>
            );
          })}
        </ol>
      ) : p.plan.days.map((d) => {
        const row = previewRows.get(d.key);
        return (
          <div key={d.key} className={`chat-plan-day${d.removed ? " is-removed" : ""}`}>
            <div className="chat-plan-day-head">
              <input type="date" className="input input-sm" value={d.date ?? ""} disabled={busy || d.removed}
                onChange={(e) => void saveDay({ ...d, date: e.target.value || null })} />
              <Text variant="caption">週{weekday(d.date)}{d.date_hint ? `・原文：${d.date_hint}` : ""}</Text>
              <span className="chat-spacer" />
              <DayControls removed={d.removed} label={d.date ?? "未定日期"} busy={busy} editing={editingKey === d.key}
                onToggleEdit={() => setEditingKey(editingKey === d.key ? null : d.key)}
                onSetRemoved={(removed) => void saveDay({ ...d, removed })} />
            </div>
            {!d.removed && (
              <>
                <pre className="chat-plan-source">{d.source}</pre>
                {d.problems.length > 0 && !d.edited && <Notice tone="critical" icon="alert">{d.problems.join("；")}（修改或刪除這一天後才能確認）</Notice>}
                {editingKey === d.key ? (
                  <DayEditor day={d} busy={busy} onSave={(day) => void saveDay(day)} />
                ) : (
                  row?.entries.map((e) => (
                    <div key={e.athlete_id} className="chat-plan-athlete">
                      <div className="chat-plan-entry">
                        <span className="chat-plan-name">{e.name}</span>
                        <Badge tone={STATUS_LABEL[e.status].tone}>{STATUS_LABEL[e.status].text}</Badge>
                      </div>
                      {e.projected_load ? (
                        <div className="field-hint">
                          ACWR 負荷比 {acwrValueText(e.projected_load.before, "zh-TW")} → 排入後 {e.projected_load.on.slice(5).replace("-", "/")}{" "}
                          {acwrValueText(e.projected_load.after, "zh-TW")}（以課表類型預估 RPE）
                        </div>
                      ) : e.load_consent === false ? (
                        <Text variant="caption" as="div">選手未授權查看訓練負荷</Text>
                      ) : null}
                      {e.status !== "skip_completed" && e.items.map((it, k) => <PlanStructure key={k} item={it} />)}
                    </div>
                  ))
                )}
              </>
            )}
          </div>
        );
      })}
      <div className="chat-card-actions">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void (async () => { await transport.dismissCard(card.id); onChanged(); })()}>取消</Button>
        {draft?.review_only ? (
          <Button size="sm" variant="primary" icon="check" disabled={busy}
            onClick={() => void (async () => {
              setBusy(true);
              onError(null);
              try { await transport.recordDraftReview(card.id, reason.trim() || undefined); onChanged(); }
              catch (e) { onError(e instanceof ApiError ? e.message : "記錄失敗"); }
              finally { setBusy(false); }
            })()}>
            記錄審核結果
          </Button>
        ) : p.plan.days.length > 0 && !weatherChanges && <Button size="sm" variant="primary" icon="check"
          disabled={busy || blocking || !!draft?.stale?.length}
          onClick={() => void (async () => {
            setBusy(true);
            onError(null);
            try {
              if (draft) await transport.confirmScheduleDraft(card.id);
              else await transport.confirmPlanCard(card.id);
              onChanged(); onConfirmed?.();
            } catch (e) {
              if (e instanceof ApiError && e.code === "WEATHER_CHANGED") {
                setWeatherChanges((e.detail?.changes as DraftWeatherChange[]) ?? []);
              } else {
                onError(e instanceof ApiError ? e.message : "排入失敗");
                if (e instanceof ApiError && e.code === "DRAFT_STALE") onChanged();
              }
            } finally { setBusy(false); }
          })()}>
          {draft ? "確認並排給選手" : "確認排入"}
        </Button>}
      </div>
      {draft && (draft.review_only || weatherChanges) && (
        <label className="field-label">修改原因（選填，會寫進審核紀錄）
          <input className="input input-sm" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
            placeholder="例如：膝蓋還在恢復，先不排穩定跑" />
        </label>
      )}
      {weatherChanges && (
        <div className="draft-weather-change">
          <strong>建立草案後天氣預報有變動</strong>
          <ul>
            {weatherChanges.map((c) => (
              <li key={c.key}>
                {c.date.slice(5).replace("-", "/")}：原本 {c.was.pace ?? "—"}（放慢 {c.was.speed_loss_pct}%）→ 最新 {c.now.pace}（放慢 {c.now.speed_loss_pct}%）
                {c.now.fetched_at && <Text variant="caption">　預報取得 {new Date(c.now.fetched_at).toLocaleString()}</Text>}
              </li>
            ))}
          </ul>
          <div className="chat-card-actions">
            <Button size="sm" variant="ghost" disabled={busy || !reason.trim()} title={reason.trim() ? undefined : "保留原配速需要填寫原因"}
              onClick={() => void (async () => {
                setBusy(true);
                try { await transport.confirmScheduleDraft(card.id, { weather: "keep", reason }); setWeatherChanges(null); onChanged(); onConfirmed?.(); }
                catch (e) { onError(e instanceof ApiError ? e.message : "排入失敗"); }
                finally { setBusy(false); }
              })()}>保留原配速並確認</Button>
            <Button size="sm" variant="primary" icon="check" disabled={busy}
              onClick={() => void (async () => {
                setBusy(true);
                try { await transport.confirmScheduleDraft(card.id, { weather: "update", reason: reason.trim() || undefined }); setWeatherChanges(null); onChanged(); onConfirmed?.(); }
                catch (e) { onError(e instanceof ApiError ? e.message : "排入失敗"); }
                finally { setBusy(false); }
              })()}>更新為最新配速並確認</Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- schedule draft (backend/app/schedule_draft.py) ---------------- */

const DRAFT_ACTION: Record<ScheduleDraftWire["week"][number]["action"], { text: string; tone: Tone }> = {
  add: { text: "新增", tone: "good" },
  adjust: { text: "建議調整", tone: "warning" },
  keep: { text: "保留教練課表", tone: "neutral" },
  locked: { text: "已完成", tone: "neutral" },
  rest: { text: "休息", tone: "neutral" },
  open: { text: "留給教練", tone: "neutral" },
};

const REASON_LABEL: Record<string, string> = {
  assigned: "教練", completed: "完成", load: "負荷", injury: "傷痛",
  weather: "天氣", health_coach: "健康教練", analysis: "課表分析", pace: "配速",
};

const ADD_KINDS = [
  { kind: "recovery", label: "恢復跑" }, { kind: "easy", label: "輕鬆跑" }, { kind: "steady", label: "穩定跑" },
  { kind: "long", label: "長距離" }, { kind: "tempo", label: "節奏跑" }, { kind: "intervals", label: "間歇" },
];

/** A workout the coach adds on a day the system left open (coach_authored). */
function AddDayForm({ date, busy, onSave, onCancel }: {
  date: string; busy: boolean; onSave: (day: PlanDayWire) => void; onCancel: () => void;
}) {
  const [kind, setKind] = useState("easy");
  const [minutes, setMinutes] = useState("40");
  const [km, setKm] = useState("");
  const [pace, setPace] = useState("");
  const [note, setNote] = useState("");
  const label = ADD_KINDS.find((k) => k.kind === kind)?.label ?? "跑步";
  const mins = Number(minutes);
  const m = pace.trim().match(/^(\d{1,2}):(\d{2})$/);
  const target = m ? Number(m[1]) * 60 + Number(m[2]) : null;
  const valid = mins > 0 && mins <= 300 && (!pace.trim() || target !== null);
  const save = () => {
    const kmN = Number(km) || 0;
    const title = `${label} ${mins} 分鐘${kmN ? ` · ${kmN} km` : ""}`;
    onSave({
      key: `c-${date}`, date, date_hint: "", source: "教練新增", problems: [], removed: false, edited: true,
      items: [{ type: "run", kind, title, notes: note.trim() || null,
        variants: { all: [{ reps: 1, distance_m: kmN ? Math.round(kmN * 1000) : null, duration_s: mins * 60,
          target_s_per_km: target, target_mode: "exact", target_text: null, rest_s: null, rest_after_s: null }] } }],
    } as unknown as PlanDayWire);
  };
  return (
    <div className="draft-add-day">
      <strong>{date.slice(5).replace("-", "/")} 新增訓練</strong>
      <div className="chat-block-edit">
        <label>類型
          <select className="input input-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
            {ADD_KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select>
        </label>
        <label>時長 分<input className="input input-sm" type="number" value={minutes} onChange={(e) => setMinutes(e.target.value)} /></label>
        <label>距離 km<input className="input input-sm" type="number" value={km} onChange={(e) => setKm(e.target.value)} /></label>
        <label>配速 分:秒<input className="input input-sm" value={pace} placeholder="5:40" onChange={(e) => setPace(e.target.value)} /></label>
      </div>
      <input className="input input-sm" value={note} maxLength={300} placeholder="給選手的備註（選填）" onChange={(e) => setNote(e.target.value)} />
      <div className="chat-card-actions">
        <Button size="sm" variant="ghost" onClick={onCancel}>取消</Button>
        <Button size="sm" variant="primary" disabled={busy || !valid} onClick={save}>加入這天</Button>
      </div>
    </div>
  );
}

/** One day's controls on a plan card: 修改 as a real secondary button, and
 *  removing the day as a quiet trash icon that asks before it acts. A removed
 *  day offers 復原 instead. */
function DayControls({ removed, label, busy, editing, onToggleEdit, onSetRemoved }: {
  removed: boolean; label: string; busy: boolean; editing: boolean;
  onToggleEdit: () => void; onSetRemoved: (removed: boolean) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  if (removed) {
    return <Button size="sm" variant="ghost" disabled={busy} onClick={() => onSetRemoved(false)}>復原</Button>;
  }
  return (
    <span className="draft-day-controls">
      <Button size="sm" variant="secondary" onClick={onToggleEdit}>{editing ? "完成" : "修改"}</Button>
      {confirming ? (
        <span className="draft-day-confirm" role="group" aria-label={`刪除 ${label}？`}>
          <Button size="sm" variant="danger" disabled={busy} onClick={() => { setConfirming(false); onSetRemoved(true); }}>確定刪除</Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>保留</Button>
        </span>
      ) : (
        <Button size="sm" variant="ghost" icon="trash" className="btn-icon draft-day-remove" disabled={busy}
          aria-label={`刪除這天（${label}）`} title="刪除這天" onClick={() => setConfirming(true)} />
      )}
    </span>
  );
}

/** The week at a glance: how many days, how far, and what it does to ACWR 負荷比. */
function DraftWeekHead({ summary }: { summary: DraftWeekSummary }) {
  const { dayCount, totalKm, acwrBefore, acwrAfter } = summary;
  return (
    <dl className="draft-summary">
      <div><dt>排課天數</dt><dd><strong>{dayCount}</strong> 天</dd></div>
      <div><dt>總里程</dt><dd><strong>{totalKm}</strong> km</dd></div>
      <div>
        <dt>ACWR 負荷比</dt>
        <dd>
          {acwrBefore !== null && acwrAfter !== null
            ? <><strong>{acwrValueText(acwrBefore, "zh-TW")}</strong> → <strong>{acwrValueText(acwrAfter, "zh-TW")}</strong></>
            : <Text variant="caption">未授權或無資料</Text>}
        </dd>
      </div>
    </dl>
  );
}

/** The whole week and why: every input that shaped it, then day by day. */
function DraftOverview({ draft, addedDates, onAdd }: {
  draft: ScheduleDraftWire; addedDates: Set<string>; onAdd?: (date: string) => void;
}) {
  const i = draft.inputs;
  const inputs: { label: string; on: boolean }[] = [
    { label: "訓練負荷", on: i.training_load },
    { label: "傷痛回報", on: i.injury },
    { label: i.weather === "forecast" ? "天氣預報" : i.weather === "observation" ? "天氣（即時推估）" : "天氣（氣候估計，非預報）",
      on: i.weather !== null },
    { label: "個人配速基準", on: !!i.easy_pace },
    { label: "健康教練對話", on: i.health_coach },
    { label: "課表分析", on: i.analysis },
    { label: `教練已排 ${i.assignments} 筆`, on: i.assignments > 0 },
  ];
  return (
    <div className="draft-overview">
      <div className="draft-inputs" aria-label="這次參考的資料">
        {inputs.map((x) => (
          <span key={x.label} className={`draft-input${x.on ? " is-on" : ""}`}>{x.on ? "✓" : "—"} {x.label}</span>
        ))}
      </div>
      <ol className="draft-week">
        {draft.week.map((d) => (
          <li key={d.date} className={`draft-day is-${d.action}`}>
            <div className="draft-day-head">
              <strong className="tnum">{d.label}</strong>
              <Badge tone={DRAFT_ACTION[d.action].tone}>{DRAFT_ACTION[d.action].text}</Badge>
              {d.action === "open" && (addedDates.has(d.date)
                ? <Badge tone="accent">教練已新增</Badge>
                : onAdd && <button type="button" className="chat-link" onClick={() => onAdd(d.date)}>新增訓練</button>)}
              <span className="draft-day-what">
                {d.proposed_text ?? (d.current.length ? d.current.join("、") : d.action === "open" ? "未排課" : "")}
                {d.action === "adjust" && d.current.length > 0 && <Text variant="caption">（原本：{d.current.join("、")}）</Text>}
              </span>
            </div>
            {d.reasons.length > 0 && (
              <ul className="draft-reasons">
                {d.reasons.map((r, k) => (
                  <li key={k} className={`draft-reason is-${r.kind}`}>
                    <span className="draft-reason-kind">{REASON_LABEL[r.kind] ?? r.kind}</span>{r.text}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function DayEditor({ day, busy, onSave }: { day: PlanDayWire; busy: boolean; onSave: (d: PlanDayWire) => void }) {
  const [draft, setDraft] = useState<PlanDayWire>(() => JSON.parse(JSON.stringify(day)));
  const setBlock = (ii: number, vk: string, bi: number, patch: Partial<PlanBlockWire>) => {
    setDraft((cur) => {
      const next: PlanDayWire = JSON.parse(JSON.stringify(cur));
      const blocks = next.items[ii].variants![vk as "all"]!;
      blocks[bi] = { ...blocks[bi], ...patch };
      return next;
    });
  };
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  return (
    <div className="chat-plan-editor">
      {draft.items.map((it, ii) => (
        <div key={ii} className="stack-sm">
          <input className="input input-sm" value={it.title}
            onChange={(e) => setDraft((cur) => { const n = JSON.parse(JSON.stringify(cur)); n.items[ii].title = e.target.value; return n; })} />
          {it.type !== "run" ? (
            <textarea className="input" rows={2} value={it.content ?? ""}
              onChange={(e) => setDraft((cur) => { const n = JSON.parse(JSON.stringify(cur)); n.items[ii].content = e.target.value; return n; })} />
          ) : (
            Object.entries(it.variants ?? {}).map(([vk, blocks]) => (
              <div key={vk}>
                <Text variant="caption" as="div">{vk === "male" ? "男生" : vk === "female" ? "女生" : "全部選手"}</Text>
                {(blocks ?? []).map((b, bi) => (
                  <div key={bi} className="chat-block-edit">
                    <label>趟數<input className="input input-sm" type="number" value={b.reps} onChange={(e) => setBlock(ii, vk, bi, { reps: Number(e.target.value) || 1 })} /></label>
                    <label>距離 m<input className="input input-sm" type="number" value={b.distance_m ?? ""} onChange={(e) => setBlock(ii, vk, bi, { distance_m: num(e.target.value) })} /></label>
                    <TargetInput block={b} onChange={(pace) => setBlock(ii, vk, bi, { target_s_per_km: pace })} />
                    <label>上限<input type="checkbox" checked={b.target_mode === "max"} onChange={(e) => setBlock(ii, vk, bi, { target_mode: e.target.checked ? "max" : "exact" })} /></label>
                    <label>趟休 秒<input className="input input-sm" type="number" value={b.rest_s ?? ""} onChange={(e) => setBlock(ii, vk, bi, { rest_s: num(e.target.value) })} /></label>
                    <label>組休 秒<input className="input input-sm" type="number" value={b.rest_after_s ?? ""} onChange={(e) => setBlock(ii, vk, bi, { rest_after_s: num(e.target.value) })} /></label>
                    <Text variant="caption">{blockLine(b)}</Text>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      ))}
      <label className="field-label">這一天的修改原因（選填）
        <input className="input input-sm" value={draft.review_reason ?? ""} maxLength={500}
          placeholder="例如：選手仍在恢復，縮短時長"
          onChange={(e) => setDraft((cur) => ({ ...cur, review_reason: e.target.value }))} />
      </label>
      <Button size="sm" variant="primary" disabled={busy} onClick={() => onSave(draft)}>儲存這一天</Button>
    </div>
  );
}

/** Target in the unit a coach writes it: seconds per rep for reps up to
 *  600 m ("37"), pace per km for longer ones ("3:45"). Stored as s/km. */
function TargetInput({ block, onChange }: { block: PlanBlockWire; onChange: (pace: number | null) => void }) {
  const perRep = !!block.distance_m && block.distance_m <= 600;
  const shown = block.target_s_per_km == null ? ""
    : perRep ? String(Math.round((block.target_s_per_km * block.distance_m!) / 1000 * 10) / 10)
    : `${Math.floor(block.target_s_per_km / 60)}:${String(Math.round(block.target_s_per_km % 60)).padStart(2, "0")}`;
  const [text, setText] = useState(shown);
  const commit = () => {
    const t = text.trim();
    if (!t) return onChange(null);
    const m = t.match(/^(d{1,2}):(d{2})$/);
    if (m) return onChange(Number(m[1]) * 60 + Number(m[2]));
    const n = Number(t);
    if (Number.isFinite(n) && n > 0 && perRep) return onChange(Math.round((n / block.distance_m!) * 1000 * 10) / 10);
    setText(shown);
  };
  return (
    <label>{perRep ? "目標 秒/趟" : "目標 分:秒/km"}
      <input className="input input-sm" value={text} placeholder={perRep ? "37" : "3:45"} onChange={(e) => setText(e.target.value)} onBlur={commit} />
    </label>
  );
}

/* ---------------- body report card ---------------- */

const SEVERITY_OPTIONS = [
  { value: "NONE", label: "無（0 分）" },
  { value: "MILD", label: "輕微（1–3 分）" },
  { value: "MODERATE", label: "中等（4–6 分）" },
  { value: "SEVERE", label: "嚴重（7–10 分）" },
] as const;

const RED_FLAG_LABEL: Record<string, string> = {
  chest_pain_or_breathing_difficulty: "胸痛或呼吸困難",
  collapse_confusion_or_extreme_heat_illness: "昏倒、意識混亂或疑似中暑",
  head_injury_with_neurological_symptoms: "頭部撞擊並有神經症狀",
  uncontrolled_bleeding: "流血不止",
  localized_bone_pain_worse_with_weight_bearing: "局部骨頭痛、踩地更痛",
  unable_to_bear_weight: "無法承重行走",
  new_numbness_or_weakness: "新出現的麻木或無力",
  hot_swollen_joint_with_fever: "關節紅腫熱痛並發燒",
  visible_deformity: "明顯變形",
};

function BodyReportCard({ card, transport, onChanged, onError }: {
  card: ChatCardWire; transport: TeamChatTransport; onChanged: () => void; onError: (e: string | null) => void;
}) {
  const p = card.payload as BodyReportPayload;
  const [busy, setBusy] = useState(false);
  const [bodyPart, setBodyPart] = useState(p.body_part ?? "");
  const [description, setDescription] = useState(p.description);
  if (card.status !== "pending") {
    // cancelled or dismissed: no trace in the chat
    return card.status === "confirmed" ? <div className="chat-card chat-card-done">身體回報已送出</div> : null;
  }
  const save = async (edit: Record<string, unknown>) => {
    setBusy(true);
    onError(null);
    try { await transport.editCard(card.id, edit); onChanged(); }
    catch (e) { onError(e instanceof ApiError ? e.message : "更新失敗"); }
    finally { setBusy(false); }
  };
  const urgent = p.triage.urgency !== "SELF_CARE_NEXT_STEP";
  return (
    <div className="chat-card">
      <div className="chat-card-head">
        <Icon name="body-status" size={16} />
        <strong>身體回報</strong>
        <Text variant="caption">只有你看得到・送出後依你的授權分享給教練</Text>
      </div>
      {urgent && (
        <Notice tone="critical" icon="alert" title={p.triage.urgency === "EMERGENCY" ? "請立即就醫" : "請儘快就醫評估"}>
          {p.triage.next_step}{p.triage.flags.length > 0 ? `（${p.triage.flags.join("、")}）` : ""}
        </Notice>
      )}
      <div className="chat-report-grid">
        <label className="field-label">部位
          <input className="input input-sm" value={bodyPart} onChange={(e) => setBodyPart(e.target.value)} onBlur={() => bodyPart !== (p.body_part ?? "") && void save({ body_part: bodyPart })} />
        </label>
        <label className="field-label">嚴重程度{p.pain_score !== null ? `（你說 ${p.pain_score} 分）` : "（請選擇）"}
          <select className="input input-sm" value={p.severity_band ?? ""} disabled={busy} onChange={(e) => void save({ severity_band: e.target.value })}>
            <option value="" disabled>選擇嚴重程度</option>
            {SEVERITY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      </div>
      <label className="field-label">描述
        <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} onBlur={() => description !== p.description && void save({ description })} />
      </label>
      <details className="chat-redflags">
        <summary>警訊症狀檢查（有勾選會提醒就醫）</summary>
        {Object.entries(RED_FLAG_LABEL).map(([k, label]) => (
          <label key={k} className="chat-check">
            <input type="checkbox" checked={!!p.red_flags[k]} disabled={busy}
              onChange={(e) => void save({ red_flags: { ...p.red_flags, [k]: e.target.checked } })} />
            {label}
          </label>
        ))}
      </details>
      <div className="chat-card-actions">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void (async () => { await transport.dismissCard(card.id); onChanged(); })()}>取消</Button>
        <Button size="sm" variant="primary" icon="check" disabled={busy || !p.severity_band}
          onClick={() => void (async () => {
            setBusy(true);
            onError(null);
            try { await transport.confirmReportCard(card.id); onChanged(); }
            catch (e) { onError(e instanceof ApiError ? e.message : "送出失敗"); }
            finally { setBusy(false); }
          })()}>
          確認送出
        </Button>
      </div>
    </div>
  );
}
