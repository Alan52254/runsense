/* Presentational primitives. Deliberately plain: each one is a function that
 * returns markup with a class name, no variant factories or style engines. */

import { useEffect, useId, useRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon.tsx";
import type { IconName } from "./Icon.tsx";
import { useLocale } from "../state/LocaleContext.tsx";

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
  label: string;
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
  checked,
  onChange,
  disabled,
}: {
  title: string;
  description: ReactNode;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="switch-row">
      <div className="switch-row-text">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="switch-row-title">{title}</span>
        </div>
        <span className="switch-row-desc">{description}</span>
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
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  children?: ReactNode;
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
      <div className="modal" ref={modalRef} tabIndex={-1}>
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
  label: string;
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

export function Avatar({ name, large }: { name: string; large?: boolean }) {
  return (
    <span className={large ? "avatar avatar-lg" : "avatar"} aria-hidden="true">
      {name.slice(-2)}
    </span>
  );
}
