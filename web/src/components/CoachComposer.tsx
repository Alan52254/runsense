import { useLayoutEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { PaperPlaneTilt } from "@phosphor-icons/react";
import { canSend, composerHeight, composerHint, composerKeyAction } from "../lib/coachComposer.ts";
import { lastUserMessage } from "../lib/coachChatUi.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";

/** One large rounded input with the send button inside it, and the privacy
 *  note under it once. Enter sends, Shift+Enter breaks the line, ArrowUp in an
 *  empty box recalls your last message. While the coach answers you can keep
 *  typing; only sending waits. */
export function CoachComposer({ en, busy }: { en: boolean; busy: boolean }) {
  const coach = useCoachChat();
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    const box = inputRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${composerHeight(box.scrollHeight, coach.input === "")}px`;
  }, [coach.input]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const action = composerKeyAction({
      key: event.key,
      shiftKey: event.shiftKey,
      // an IME confirming a Chinese word is not a send
      composing: event.nativeEvent.isComposing || event.keyCode === 229,
      input: coach.input,
      lastUserMessage: lastUserMessage(coach.messages),
    });
    if (action.kind === "send") {
      event.preventDefault();
      void coach.send();
    } else if (action.kind === "recall") {
      event.preventDefault();
      coach.setInput(action.text);
    }
  };

  const placeholder =
    composerHint(busy) === "busy"
      ? en ? "Replying… you can type ahead" : "教練回覆中，可以先打下一題"
      : en ? "Ask about your run or how you feel…" : "問課表、配速，或說說身體感覺…";

  return (
    <footer className="cc-composer">
      <form
        className="cc-box"
        onSubmit={(event) => {
          event.preventDefault();
          void coach.send();
        }}
      >
        <textarea
          ref={inputRef}
          rows={1}
          className="cc-input"
          value={coach.input}
          onChange={(event) => coach.setInput(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label={en ? "Message to your coach" : "給教練的訊息"}
          placeholder={placeholder}
        />
        <button type="submit" className="btn btn-primary cc-send" disabled={!canSend(coach.input, busy)}>
          <PaperPlaneTilt size={16} weight="bold" aria-hidden="true" />
          <span className="cc-send-label">{en ? "Send" : "發送"}</span>
        </button>
      </form>
      <p className="cc-privacy">
        {en
          ? "Messages and the training data needed to answer are processed by a cloud model; no names, emails or accounts are sent."
          : "對話與回答所需的訓練資料會送到雲端模型處理，不含姓名、Email 或帳號。"}
      </p>
    </footer>
  );
}
