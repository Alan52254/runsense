import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

export type SurfaceDepth = "outer" | "inner" | "interactive";
export type SurfacePadding = "none" | "sm" | "md" | "lg";
export type SurfaceTone = "neutral" | "brand" | "good" | "warning" | "danger";
type SurfaceOwnProps<T extends ElementType> = {
  as?: T;
  depth?: SurfaceDepth;
  padding?: SurfacePadding;
  tone?: SurfaceTone;
  header?: ReactNode;
  children?: ReactNode;
  className?: string;
};
export type SurfaceProps<T extends ElementType = "div"> = SurfaceOwnProps<T> &
  Omit<ComponentPropsWithoutRef<T>, keyof SurfaceOwnProps<T>>;

/** Owns panel material and spacing. Callers supply content and layout only. */
export function Surface<T extends ElementType = "div">({
  as, depth = "outer", padding = "md", tone = "neutral", header, children, className, ...rest
}: SurfaceProps<T>) {
  const Tag = as ?? "div";
  return <Tag {...rest} className={["rs-surface", className].filter(Boolean).join(" ")}
    data-depth={depth} data-padding={padding} data-tone={tone}>
    {header != null && <header className="rs-surface__header">{header}</header>}
    {children}
  </Tag>;
}

/** Compatibility at the public UI boundary; CSS sees one tone vocabulary. */
export function semanticTone(tone: "neutral" | "accent" | "good" | "warning" | "serious" | "critical") {
  return tone === "accent" ? "brand" : tone === "critical" ? "danger" : tone === "serious" ? "warning" : tone;
}
