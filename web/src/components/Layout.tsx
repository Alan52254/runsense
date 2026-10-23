import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

/** Spacing steps 1-6 = 4/8/12/16/20/24px (the --s-1..s-6 scale). */
export type Gap = 1 | 2 | 3 | 4 | 5 | 6;
type Align = "start" | "center" | "end" | "baseline" | "stretch";
type Justify = "start" | "center" | "end" | "between";

type LayoutOwnProps<T extends ElementType> = {
  as?: T;
  gap?: Gap;
  children?: ReactNode;
  className?: string;
};
type LayoutProps<T extends ElementType, Extra = object> = LayoutOwnProps<T> & Extra &
  Omit<ComponentPropsWithoutRef<T>, keyof LayoutOwnProps<T> | keyof Extra>;

function join(base: string, className?: string) {
  return className ? `${base} ${className}` : base;
}

/** Vertical group; children are separated by `gap`. */
export function Stack<T extends ElementType = "div">(
  { as, gap = 3, className, ...rest }: LayoutProps<T, { align?: Align }>,
) {
  const Tag = as ?? "div";
  const { align, ...props } = rest as { align?: Align };
  return <Tag {...props} className={join("rs-stack", className)} data-gap={gap} data-align={align} />;
}

/** Horizontal group on one line (or wrapping when `wrap`). */
export function Row<T extends ElementType = "div">(
  { as, gap = 2, className, ...rest }: LayoutProps<T, { align?: Align; justify?: Justify; wrap?: boolean }>,
) {
  const Tag = as ?? "div";
  const { align, justify, wrap, ...props } = rest as { align?: Align; justify?: Justify; wrap?: boolean };
  return <Tag {...props} className={join("rs-row", className)} data-gap={gap} data-align={align}
    data-justify={justify} data-wrap={wrap ? "" : undefined} />;
}

/** Inline group that wraps when it runs out of room (chips, badges, actions). */
export function Cluster<T extends ElementType = "div">(
  { as, gap = 2, className, ...rest }: LayoutProps<T, { align?: Align; justify?: Justify }>,
) {
  const Tag = as ?? "div";
  const { align, justify, ...props } = rest as { align?: Align; justify?: Justify };
  return <Tag {...props} className={join("rs-cluster", className)} data-gap={gap} data-align={align}
    data-justify={justify} />;
}
