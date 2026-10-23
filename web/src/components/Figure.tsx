import { formatByKind, type FigureSpec } from "../lib/figureFormat.ts";

export type FigureProps = FigureSpec & { className?: string };

/** A run number (pace, duration, distance) in the number font with a quieter unit. */
export function Figure({ className, ...spec }: FigureProps) {
  const { value, unit } = formatByKind(spec as FigureSpec);
  return (
    <span className={className ? `rs-figure ${className}` : "rs-figure"}>
      <span className="rs-figure__val">{value}</span>
      {unit ? <span className="rs-figure__unit">{unit}</span> : null}
    </span>
  );
}
