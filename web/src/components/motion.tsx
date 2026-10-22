/* v2 motion and glass primitives. Framer Motion supplies springs, tilt and
 * slides only; every look comes from styles/glass.css and the tokens.
 * Reduced motion turns off tilt, marquee and springs; tilt also needs a
 * fine pointer. */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { CSSProperties, Ref, HTMLAttributes, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  AnimatePresence,
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from "framer-motion";
import type { Transition } from "framer-motion";
import { Icon } from "./Icon.tsx";
import type { IconName } from "./Icon.tsx";
import { wrapFocusIndex } from "../lib/coachChatSession.ts";

/* ---------------- shared springs ---------------- */

export const SPRING_TILT = { stiffness: 400, damping: 30 } as const;
export const SPRING_RAIL: Transition = { type: "spring", stiffness: 350, damping: 25 };
export const SPRING_DRAWER: Transition = { type: "spring", duration: 0.4, bounce: 0 };
const INSTANT: Transition = { duration: 0 };

function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(" ");
}

/** true while the device has a precise pointer (mouse, trackpad). */
export function useFinePointer(): boolean {
  const query = "(pointer: fine)";
  const [fine, setFine] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const update = () => setFine(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  return fine;
}

/* ---------------- GlassPanel ---------------- */

type GlassTag = "div" | "section" | "article" | "aside" | "header" | "footer";

export interface GlassPanelProps extends HTMLAttributes<HTMLElement> {
  /** "outer" = 24px container, "inner" = 16px interactive card. */
  variant?: "outer" | "inner";
  as?: GlassTag;
  /** inner padding on the token scale; "none" for flush content. */
  padding?: "none" | "sm" | "md" | "lg";
}

/** Dark frosted glass: blur, a 1px light edge, an offset soft shadow. */
export function GlassPanel({
  variant = "outer",
  as: Tag = "div",
  padding = "md",
  className,
  children,
  ...rest
}: GlassPanelProps) {
  return (
    <Tag
      className={cx("glass", `glass--${variant}`, padding !== "none" && `glass--pad-${padding}`, className)}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/* ---------------- TiltCard ---------------- */

export interface TiltCardProps extends Omit<HTMLAttributes<HTMLDivElement>, "onPointerMove" | "onPointerLeave" | "style"> {
  /** maximum tilt in degrees on each axis (spec: 8). */
  maxTilt?: number;
  /** the orange specular glow that follows the pointer. */
  specular?: boolean;
  style?: CSSProperties;
  children: ReactNode;
}

/** The hero's 3D tilt. rotateX = ((y - cy)/cy) * -max, rotateY =
 *  ((x - cx)/cx) * max, scale 1.01 on hover, spring 400/30. Children can
 *  lift with the `.tilt-layer` class (translateZ 32px). Static under reduced
 *  motion or a coarse pointer. */
export function TiltCard({
  maxTilt = 8,
  specular = true,
  className,
  style,
  children,
  ...rest
}: TiltCardProps) {
  const reduce = useReducedMotion();
  const fine = useFinePointer();
  const enabled = fine && !reduce;

  const rotateX = useSpring(0, SPRING_TILT);
  const rotateY = useSpring(0, SPRING_TILT);
  const scale = useSpring(1, SPRING_TILT);
  const glowX = useMotionValue(0);
  const glowY = useMotionValue(0);
  const glowOpacity = useSpring(0, SPRING_TILT);
  const glow = useMotionTemplate`radial-gradient(circle 350px at ${glowX}px ${glowY}px, rgba(255, 107, 0, 0.12), transparent 80%)`;

  const onMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!enabled || event.pointerType !== "mouse") return;
      const box = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - box.left;
      const y = event.clientY - box.top;
      const cxPx = box.width / 2;
      const cyPx = box.height / 2;
      rotateX.set(((y - cyPx) / cyPx) * -maxTilt);
      rotateY.set(((x - cxPx) / cxPx) * maxTilt);
      scale.set(1.01);
      glowX.set(x);
      glowY.set(y);
      glowOpacity.set(1);
    },
    [enabled, maxTilt, rotateX, rotateY, scale, glowX, glowY, glowOpacity],
  );

  const onLeave = useCallback(() => {
    rotateX.set(0);
    rotateY.set(0);
    scale.set(1);
    glowOpacity.set(0);
  }, [rotateX, rotateY, scale, glowOpacity]);

  if (!enabled) {
    return (
      <div className={cx("tilt", className)} style={style} {...rest}>
        {children}
      </div>
    );
  }

  return (
    <div className="tilt-stage">
      <motion.div
        className={cx("tilt", "is-tilting", className)}
        style={{ ...style, rotateX, rotateY, scale, transformStyle: "preserve-3d" }}
        onPointerMove={onMove}
        onPointerLeave={onLeave}
        {...(rest as object)}
      >
        {specular && (
          <motion.span
            aria-hidden="true"
            className="tilt-specular"
            style={{ background: glow, opacity: glowOpacity }}
          />
        )}
        {children}
      </motion.div>
    </div>
  );
}

/* ---------------- SlideOver ---------------- */

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface SlideOverProps {
  open: boolean;
  onClose: () => void;
  /** id of the visible title inside `children`. */
  labelledBy: string;
  describedBy?: string;
  /** "md" 560px (coach), "lg" 960px (analysis tables), "xl" 1040px (team
   *  chat with its room list). Phones get full width. */
  size?: "md" | "lg" | "xl";
  /** CSS selector of the element to focus on open; falls back to the panel. */
  initialFocus?: string;
  className?: string;
  children: ReactNode;
}

/** The one right-hand drawer: slides in on a 400ms spring over a fading
 *  scrim. While open the page behind is inert, Tab stays inside, Esc and a
 *  scrim click close it, and focus returns to whatever opened it. */
export function SlideOver({
  open,
  onClose,
  labelledBy,
  describedBy,
  size = "md",
  initialFocus,
  className,
  children,
}: SlideOverProps) {
  const reduce = useReducedMotion();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const initialFocusRef = useRef(initialFocus);
  initialFocusRef.current = initialFocus;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    const previousOverflow = document.body.style.overflow;
    if (root) root.inert = true;
    document.body.style.overflow = "hidden";
    const panel = panelRef.current;
    const selector = initialFocusRef.current;
    const first = (selector && panel?.querySelector<HTMLElement>(selector)) || panel;
    first?.focus({ preventScroll: true });

    function onKeyDown(event: KeyboardEvent) {
      const sheet = panelRef.current;
      if (!sheet) return;
      // a dialog stacked above the drawer handles its own keys
      if (event.target instanceof Node && !sheet.contains(event.target) && event.target !== document.body) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.getClientRects().length > 0,
      );
      const index = focusables.indexOf(document.activeElement as HTMLElement);
      const target = wrapFocusIndex(focusables.length, index, event.shiftKey);
      if (target !== null) {
        event.preventDefault();
        focusables[target].focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (root) root.inert = wasInert;
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="slide-over-root" key="slide-over">
          <motion.div
            className="slide-over-scrim"
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={reduce ? INSTANT : { duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            onMouseDown={() => onCloseRef.current()}
          />
          <motion.div
            ref={panelRef}
            className={cx("slide-over", `slide-over--${size}`, className)}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            aria-describedby={describedBy}
            tabIndex={-1}
            initial={reduce ? { x: 0, opacity: 0 } : { x: "100%" }}
            animate={reduce ? { x: 0, opacity: 1 } : { x: 0 }}
            exit={reduce ? { x: 0, opacity: 0 } : { x: "100%" }}
            transition={reduce ? INSTANT : SPRING_DRAWER}
          >
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/* ---------------- Ticker ---------------- */

export interface TickerItem {
  id: string;
  icon: IconName;
  text: ReactNode;
  /** colour of the icon; the text says the state in words. */
  tone?: "neutral" | "climate" | "safe" | "alert" | "brand";
}

export interface TickerProps {
  items: TickerItem[];
  /** accessible name of the strip, e.g. 即時狀態. */
  label: string;
  /** opens the details (environment drawer); renders a button when given. */
  onOpenDetails?: () => void;
  detailsLabel?: string;
  className?: string;
}

function TickerRun({ items, hidden, runRef }: {
  items: TickerItem[];
  hidden?: boolean;
  runRef?: Ref<HTMLUListElement>;
}) {
  return (
    <ul className="ticker-run" aria-hidden={hidden || undefined} ref={runRef}>
      {items.map((item) => (
        <li key={item.id} className={cx("ticker-item", item.tone && `is-${item.tone}`)}>
          <Icon name={item.icon} size={15} />
          <span>{item.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Live ambient status strip. A seamless CSS marquee that pauses on hover
 *  and focus; it only moves when the items overflow the strip, and under
 *  reduced motion the items sit still and wrap. */
export function Ticker({ items, label, onOpenDetails, detailsLabel, className }: TickerProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const runRef = useRef<HTMLUListElement | null>(null);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    const run = runRef.current;
    if (!viewport || !run || typeof ResizeObserver === "undefined") return;
    const measure = () => setOverflows(run.scrollWidth > viewport.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    observer.observe(run);
    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;
  // long enough to read: about 6s per item, never faster than 24s a loop
  const duration = `${Math.max(24, items.length * 6)}s`;
  return (
    <div className={cx("ticker", overflows && "is-moving", className)} role="region" aria-label={label}>
      <div className="ticker-viewport" ref={viewportRef}>
        <div className="ticker-track" style={{ "--ticker-duration": duration } as CSSProperties}>
          <TickerRun items={items} runRef={runRef} />
          {overflows && <TickerRun items={items} hidden />}
        </div>
      </div>
      {onOpenDetails && (
        <button
          type="button"
          className="ticker-details"
          onClick={onOpenDetails}
          aria-label={detailsLabel}
          title={detailsLabel}
        >
          <Icon name="info" size={16} />
        </button>
      )}
    </div>
  );
}

/* ---------------- Rail ---------------- */

export interface RailStage {
  id: string;
  title: ReactNode;
  /** always visible: e.g. duration or distance. */
  meta?: ReactNode;
  /** shown when the stage is focused: e.g. pace and heart-rate range. */
  detail?: ReactNode;
  icon?: IconName;
}

export interface RailProps {
  stages: RailStage[];
  /** accessible name of the rail, e.g. 課表結構. */
  label: string;
  /** a stage was pressed (click / Enter / Space). */
  onSelect?: (id: string) => void;
  className?: string;
}

/** Horizontal stage rail (warm-up, main set, cool-down). Overlapped at rest,
 *  slides apart into a timeline on hover or focus; the focused stage lifts
 *  (y -6, scale 1.02) and shows its detail while the others dim (.6 / .96).
 *  Stacks vertically on phones. */
export function Rail({ stages, label, onSelect, className }: RailProps) {
  const reduce = useReducedMotion();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [inside, setInside] = useState(false);
  const detailIdBase = useId();
  const expanded = inside || activeId !== null;

  const onKeyDown = (event: ReactKeyboardEvent<HTMLOListElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".rail-stage"));
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    buttons[(index + step + buttons.length) % buttons.length]?.focus();
  };

  return (
    <ol
      className={cx("rail", expanded && "is-expanded", className)}
      aria-label={label}
      onPointerEnter={() => setInside(true)}
      onPointerLeave={() => {
        setInside(false);
        setActiveId((current) => (document.activeElement?.closest(".rail") ? current : null));
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setActiveId(null);
      }}
      onKeyDown={onKeyDown}
    >
      {stages.map((stage, index) => {
        const state = activeId === null ? "rest" : activeId === stage.id ? "focus" : "dim";
        const detailId = `${detailIdBase}-${index}`;
        return (
          <motion.li
            key={stage.id}
            className="rail-item"
            style={{ zIndex: state === "focus" ? stages.length + 1 : stages.length - index }}
            animate={
              state === "focus"
                ? { opacity: 1, y: -6, scale: 1.02 }
                : state === "dim"
                  ? { opacity: 0.6, y: 0, scale: 0.96 }
                  : { opacity: 1, y: 0, scale: 1 }
            }
            transition={reduce ? INSTANT : SPRING_RAIL}
          >
            <button
              type="button"
              className={cx("rail-stage", state === "focus" && "is-focused")}
              aria-describedby={stage.detail ? detailId : undefined}
              onPointerEnter={() => setActiveId(stage.id)}
              onFocus={() => setActiveId(stage.id)}
              onClick={() => onSelect?.(stage.id)}
            >
              <span className="rail-stage-head">
                {stage.icon && <Icon name={stage.icon} size={16} />}
                <span className="rail-stage-title">{stage.title}</span>
              </span>
              {stage.meta && <span className="rail-stage-meta">{stage.meta}</span>}
              {stage.detail && (
                <span className="rail-stage-detail" id={detailId}>
                  <span>{stage.detail}</span>
                </span>
              )}
            </button>
          </motion.li>
        );
      })}
    </ol>
  );
}
