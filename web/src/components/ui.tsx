/* Presentational primitives. Deliberately plain: each one is a function that
 * returns markup with a class name, no variant factories or style engines. */

import { useEffect, useId, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon.tsx";
import type { IconName } from "./Icon.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { tooltipTransform } from "../lib/tooltipPosition.ts";

export type Tone = "neutral" | "accent" | "good" | "warning" | "serious" | "critical";

/* ---------------- Card ---------------- */

export function Card({
  title,
  subtitle,
  actions,
  children,
  footer,
  flush,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={className ? `card ${className}` : "card"}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <h2 className="card-title">{title}</h2>
            </div>
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className={flush ? "card-body card-body-flush" : "card-body"}>{children}</div>
      {footer && <footer className="card-footer">{footer}</footer>}
    </section>
  );
}

/* ---------------- Badge ---------------- */

export function Badge({
  tone = "neutral",
  dot,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={tone === "neutral" ? "badge" : `badge badge-${tone}`}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  );
}

/* ---------------- Button ---------------- */

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: IconName;
  block?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  block,
  children,
  className,
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    `btn-${variant}`,
    size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "",
    block ? "btn-block" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button className={classes} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 15 : 16} />}
      {children}
    </button>
  );
}

/* ---------------- Form ---------------- */

export function Field({
  label,
  hint,
  error,
  htmlFor,
  labelAside,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  htmlFor?: string;
  labelAside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <div className="field-label-row">
        <label className="field-label" htmlFor={htmlFor}>
          {label}
        </label>
        {labelAside}
      </div>
      {children}
      {error ? (
        <span className="field-error">{error}</span>
      ) : hint ? (
        <span className="field-hint">{hint}</span>
      ) : null}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="switch"
      data-on={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-knob" />
    </button>
  );
}

export function SwitchRow({
  title,
  description,
  hint,
  checked,
  onChange,
  disabled,
  large,
}: {
  title: string;
  description?: ReactNode;
  /** Short explanatory text shown behind an (i) icon next to the title,
   *  instead of always-visible description text below it. */
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** Sizes the title to match .card-title, for a switch row standing in for
   *  a card header (e.g. a lone toggle that's the only thing in its card). */
  large?: boolean;
}) {
  return (
    <div className="switch-row">
      <div className="switch-row-text">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className={large ? "switch-row-title switch-row-title-lg" : "switch-row-title"}>{title}</span>
          {hint && <InfoTip text={hint} />}
        </div>
        {description && <span className="switch-row-desc">{description}</span>}
      </div>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={title} />
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (next: T) => void;
}) {
  return (
    <div className="segmented">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export interface DateRange {
  from: string;
  to: string;
}

/** A from/to pair of native date inputs for browsing a chart's date range,
 *  e.g. the dashboard's daily-load and daily-distance charts (both default
 *  to the last 28 days, but can be widened/narrowed independently). Keeps
 *  from <= to <= maxDate by clamping the other bound on change, since a
 *  typed-in date can bypass the input's own min/max constraints in some
 *  browsers. */
export function DateRangePicker({
  range,
  maxDate,
  defaultRange,
  onChange,
}: {
  range: DateRange;
  maxDate: string;
  defaultRange: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const { locale } = useLocale();
  const en = locale === "en";
  const isDefault = range.from === defaultRange.from && range.to === defaultRange.to;

  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <input
        className="input"
        style={{ width: 148, height: 38 }}
        type="date"
        value={range.from}
        max={range.to}
        aria-label={en ? "From date" : "起始日期"}
        onChange={(e) => {
          const from = e.target.value;
          if (!from) return;
          onChange({ from, to: from > range.to ? from : range.to });
        }}
      />
      <span className="field-hint">{en ? "to" : "至"}</span>
      <input
        className="input"
        style={{ width: 148, height: 38 }}
        type="date"
        value={range.to}
        min={range.from}
        max={maxDate}
        aria-label={en ? "To date" : "結束日期"}
        onChange={(e) => {
          const to = e.target.value > maxDate ? maxDate : e.target.value;
          if (!to) return;
          onChange({ from: to < range.from ? to : range.from, to });
        }}
      />
      {!isDefault && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(defaultRange)}>
          {en ? "Reset to 28 days" : "重設為近 28 天"}
        </button>
      )}
    </div>
  );
}

/* ---------------- Feedback ---------------- */

export function Notice({
  tone = "neutral",
  title,
  icon = "info",
  children,
}: {
  tone?: "neutral" | "accent" | "warning" | "critical";
  title?: string;
  icon?: IconName;
  children: ReactNode;
}) {
  return (
    <div className={tone === "neutral" ? "notice" : `notice notice-${tone}`}>
      <span className="notice-icon">
        <Icon name={icon} size={16} />
      </span>
      <div>
        {title && (
          <div className="notice-title" style={{ marginBottom: 2 }}>
            {title}
          </div>
        )}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({
  icon = "search",
  title,
  description,
  action,
}: {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={18} />
      </span>
      <span className="empty-title">{title}</span>
      {description && <span className="empty-desc">{description}</span>}
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

/* ---------------- Modal ---------------- */

export function Modal({
  open,
  title,
  description,
  onClose,
  footer,
  children,
  size = "md",
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  children?: ReactNode;
  /** "lg" widens the modal for data-dense forms like the workout builder. */
  size?: "md" | "lg";
}) {
  const { t } = useLocale();
  const titleId = useId();
  const modalRef = useRef<HTMLDivElement | null>(null);
  // onClose is typically a fresh inline function every render; keeping it out
  // of the effect's deps (via this ref) stops the focus effect below from
  // re-firing on every keystroke inside the modal and stealing focus back to
  // the modal wrapper after each character.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    modalRef.current?.focus();

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      previouslyFocused?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={size === "lg" ? "modal modal-lg" : "modal"} ref={modalRef} tabIndex={-1}>
        <div className="modal-header">
          <div className="row-between">
            <h2 className="modal-title" id={titleId}>{title}</h2>
            <Button variant="ghost" size="sm" icon="x" onClick={onClose} aria-label={t("close")} />
          </div>
          {description && <p className="modal-desc">{description}</p>}
        </div>
        {children && <div className="modal-body">{children}</div>}
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------------- Stat tile ---------------- */

export function StatTile({
  label,
  value,
  unit,
  foot,
  small,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  foot?: ReactNode;
  small?: boolean;
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={small ? "stat-value stat-value-sm" : "stat-value"}>
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </span>
      {foot &&
        (typeof foot === "string" ? <span className="stat-foot">{foot}</span> : foot)}
    </div>
  );
}

/* ---------------- Info tip ---------------- */

/** A small (i) icon that reveals an explanatory bubble on hover/focus --
 *  pass `children` to use a different trigger (e.g. the value itself)
 *  instead of the default icon. Positioned with `position: fixed` from the
 *  trigger's own bounding rect (not `position: absolute` within whatever
 *  card contains it), the same way chart tooltips are -- so the bubble
 *  escapes the card's own `overflow: hidden` and flips against the real
 *  viewport edges instead of clipping against the card. */
export function InfoTip({ text, children }: { text: string; children?: ReactNode }) {
  const triggerRef = useRef<HTMLSpanElement>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);

  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setAnchor({ x: rect.left, y: rect.bottom });
  };
  const hide = () => setAnchor(null);

  return (
    <span
      ref={triggerRef}
      className="info-tip"
      tabIndex={0}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children ?? (
        <span className="info-tip-icon">
          <Icon name="info" size={12} />
        </span>
      )}
      {anchor && (
        <span
          className="info-tip-bubble"
          style={{ left: anchor.x, top: anchor.y, transform: tooltipTransform(anchor.x, anchor.y, 300) }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

export function Avatar({ name, large }: { name: string; large?: boolean }) {
  return (
    <span className={large ? "avatar avatar-lg" : "avatar"} aria-hidden="true">
      {name.slice(-2)}
    </span>
  );
}
