import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";
import type { SurfaceTone } from "./Surface.tsx";

export type TextRole = "heading-lg" | "heading-md" | "body" | "caption" | "label" | "figure";

type TextOwnProps<T extends ElementType> = {
  as?: T;
  variant?: TextRole;
  tone?: SurfaceTone;
  children?: ReactNode;
  className?: string;
};
export type TextProps<T extends ElementType = "span"> = TextOwnProps<T> &
  Omit<ComponentPropsWithoutRef<T>, keyof TextOwnProps<T>>;

const DEFAULT_TAG: Record<TextRole, ElementType> = {
  "heading-lg": "h2", "heading-md": "h3", body: "p", caption: "span", label: "span", figure: "span",
};

/** One typographic role from the DESIGN.md scale; callers never set size or weight. */
export function Text<T extends ElementType = "span">(
  { as, variant = "body", tone, className, ...rest }: TextProps<T>,
) {
  const Tag = as ?? DEFAULT_TAG[variant];
  return <Tag {...rest} className={className ? `rs-text ${className}` : "rs-text"}
    data-variant={variant} data-tone={tone} />;
}
