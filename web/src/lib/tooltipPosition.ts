/* Shared positioning for every floating tooltip/info-bubble in the app
 * (chart hover tooltips, info-tip icons, ...). All of them render with
 * `position: fixed` and use viewport coordinates (not container-relative
 * ones), so a tooltip escapes any ancestor's `overflow: hidden` clipping
 * and flips against the real page edges -- not against whichever card
 * happens to contain the trigger. A trigger near a card's own edge with
 * open space just past it (a left-column chart, a stat tile mid-row) must
 * NOT flip just because it's near *that card's* edge -- only the actual
 * viewport edge matters. */

export const TOOLTIP_GAP = 14;

/** Anchors below-and-right of the trigger point by default, then flips
 *  toward whichever side has room against the actual browser viewport --
 *  leftward if it would run off the right edge of the page, upward if it
 *  would run off the bottom. No ref to measure the actual rendered box
 *  against before first paint, so estWidth/estHeight are deliberately
 *  generous estimates -- better to flip a little early than to let it clip
 *  off-screen. */
export function tooltipTransform(
  anchorX: number,
  anchorY: number,
  estWidth = 220,
  estHeight = 120,
): string {
  const tx = anchorX + estWidth > window.innerWidth ? "-100%" : "0";
  const ty =
    anchorY + TOOLTIP_GAP + estHeight > window.innerHeight
      ? `calc(-100% - ${TOOLTIP_GAP}px)`
      : `${TOOLTIP_GAP}px`;
  return `translate(${tx}, ${ty})`;
}
