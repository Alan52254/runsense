import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import mark96 from "../assets/brand/brand-mark-96.webp";
import mark192 from "../assets/brand/brand-mark-192.webp";
import runner72 from "../assets/brand/brand-runner-72.webp";
import runner192 from "../assets/brand/brand-runner-192.webp";
import loginBoard from "../assets/brand/login-board.webp";
import { BRAND_PX, brandFiles, legibleVariant } from "../lib/brandMark.ts";
import type { BrandFile, BrandSize, BrandVariant } from "../lib/brandMark.ts";

const FILES: Record<BrandFile, string> = {
  "mark-96": mark96,
  "mark-192": mark192,
  "runner-72": runner72,
  "runner-192": runner192,
};

/** The one place the RunSense logo is drawn: the supplied "edge AI coach"
 *  runner. `mark` is the rounded tile (sidebar, login); `runner` is the figure
 *  alone in a circle, for small sizes and the 健康教練's face. While the coach
 *  works a ring breathes around it (opacity and scale only); when the answer
 *  is done the ring settles once. */
export function BrandMark({
  variant = "mark",
  size = "md",
  state = "idle",
}: {
  variant?: BrandVariant;
  size?: BrandSize;
  state?: "idle" | "thinking";
}) {
  const shown = legibleVariant(variant, size);
  const files = brandFiles(shown, size);
  const px = BRAND_PX[size];

  // thinking then idle is a settle, played once; idle on first paint is not
  const [settling, setSettling] = useState(false);
  const previous = useRef(state);
  useEffect(() => {
    if (previous.current === "thinking" && state === "idle") setSettling(true);
    if (state === "thinking") setSettling(false);
    previous.current = state;
  }, [state]);

  return (
    <span
      className={`bm bm--${shown} bm--${size}`}
      data-state={state}
      data-settled={settling || undefined}
      onAnimationEnd={() => setSettling(false)}
      style={{ "--bm-size": `${px}px` } as CSSProperties}
      aria-hidden="true"
    >
      <img
        className="bm-img"
        src={FILES[files.x1]}
        srcSet={`${FILES[files.x1]} 1x, ${FILES[files.x2]} 2x`}
        width={px}
        height={px}
        alt=""
        decoding="async"
      />
    </span>
  );
}

/** The login brand panel's backdrop: the supplied circuit board. Decorative;
 *  the panel's own veil keeps its text readable over it. */
export function BrandBackdrop() {
  return <img className="bm-backdrop" src={loginBoard} alt="" decoding="async" />;
}
