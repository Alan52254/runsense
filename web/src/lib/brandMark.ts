/** The RunSense logo's sizes and which raster serves them, without React.
 *  BrandMark.tsx is the only module that shows the logo; this is its table. */

export type BrandVariant = "mark" | "runner";
export type BrandSize = "sm" | "md" | "lg" | "xl";

/** Rendered pixel size of each step. sm sits beside a message, md is the
 *  sidebar and headers (the persona avatars' 36px), lg the opening state and
 *  login, xl the login brand panel. */
export const BRAND_PX: Record<BrandSize, number> = { sm: 28, md: 36, lg: 64, xl: 96 };

export type BrandFile = "mark-96" | "mark-192" | "runner-72" | "runner-192";

/** The runner has two rasters: a thickened 72px one tuned to stay legible at
 *  28 to 36px, and a 192px one for 64px and up. The tile has one pair, 96px
 *  and its 2x. Returns the 1x and 2x files. */
export function brandFiles(variant: BrandVariant, size: BrandSize): { x1: BrandFile; x2: BrandFile } {
  if (variant === "mark") return { x1: "mark-96", x2: "mark-192" };
  return BRAND_PX[size] <= 36 ? { x1: "runner-72", x2: "runner-72" } : { x1: "runner-192", x2: "runner-192" };
}

/** The tile is too detailed under 36px: it falls back to the runner. */
export function legibleVariant(variant: BrandVariant, size: BrandSize): BrandVariant {
  return variant === "mark" && BRAND_PX[size] < 36 ? "runner" : variant;
}
