import { useCallback, useEffect, useRef, useState } from "react";
import { shouldStickToBottom, startsAtTop } from "../lib/coachChatUi.ts";
import { useMotion } from "./motion.tsx";

/** Follow the conversation only while the reader is near its end. Scrolled up
 *  mid-answer, they are reading: leave them there and offer 新回覆. */
export function useStickToEnd(input: { active: boolean; sentCount: number; streaming: boolean; version: unknown }) {
  const { active, sentCount, streaming, version } = input;
  const { reduce } = useMotion();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);
  const programmatic = useRef(false);
  const [behind, setBehind] = useState(false);

  const scrollToEnd = useCallback(
    (smooth: boolean) => {
      const el = scrollRef.current;
      if (!el) return;
      const animate = smooth && !reduce;
      programmatic.current = true;
      el.scrollTo({ top: el.scrollHeight, behavior: animate ? "smooth" : "instant" });
      window.setTimeout(() => {
        programmatic.current = false;
      }, animate ? 500 : 60);
    },
    [reduce],
  );

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || programmatic.current) return;
    const near = shouldStickToBottom(el.scrollTop, el.clientHeight, el.scrollHeight);
    stick.current = near;
    if (near) setBehind(false);
  };
  // the reader taking the wheel or a finger to the thread outranks our own scroll
  const takeOver = () => {
    programmatic.current = false;
  };
  // wheeling up is leaving the end, even before the first scroll event says so
  const onWheel = (event: { deltaY: number }) => {
    takeOver();
    if (event.deltaY < 0) stick.current = false;
  };

  const lastSentCount = useRef(sentCount);
  useEffect(() => {
    if (!active) {
      scrollRef.current?.scrollTo({ top: 0, behavior: "instant" });
      return;
    }
    const justAsked = sentCount !== lastSentCount.current;
    lastSentCount.current = sentCount;
    if (justAsked) stick.current = true;
    if (startsAtTop(sentCount)) {
      scrollRef.current?.scrollTo({ top: 0, behavior: "instant" });
      setBehind(false);
    } else if (stick.current) {
      scrollToEnd(!streaming);
      setBehind(false);
    } else {
      setBehind(true);
    }
  }, [version, active, sentCount, streaming, scrollToEnd]);
  useEffect(() => {
    if (active) {
      stick.current = true;
      setBehind(false);
    }
  }, [active]);

  const jump = () => {
    stick.current = true;
    scrollToEnd(true);
    setBehind(false);
  };

  return { scrollRef, behind: active && behind, jump, bind: { onScroll, onWheel, onTouchMove: takeOver } };
}
