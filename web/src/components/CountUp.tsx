import { useEffect, useRef, useState } from "react";
import { countUpValue } from "../lib/coachChatUi.ts";
import { MOTION, useMotion } from "./motion.tsx";

/** What each figure last showed, so a panel that mounts again (the drawer
 *  reopened, the page visited) counts from there instead of from zero. */
const lastShown = new Map<string, number>();

/** A figure that counts to its real value once, over --motion-emphasis.
 *  A missing value is shown as an em dash and never counted. Reduced motion
 *  shows the value at once. */
export function CountUp({ id, value, decimals = 0 }: { id: string; value: number | null; decimals?: number }) {
  const { reduce } = useMotion();
  const [shown, setShown] = useState<number>(() =>
    value === null || reduce ? (value ?? 0) : (lastShown.get(id) ?? 0),
  );
  const current = useRef(shown);
  current.current = shown;

  useEffect(() => {
    if (value === null) return;
    const from = current.current;
    lastShown.set(id, value);
    if (reduce || from === value) {
      setShown(value);
      return;
    }
    const duration = MOTION.emphasis * 1000;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = (now - start) / duration;
      setShown(countUpValue(from, value, progress, decimals));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [id, value, decimals, reduce]);

  return <>{value === null ? "—" : shown.toFixed(decimals)}</>;
}
