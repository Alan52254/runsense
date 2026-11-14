import { RunMap3D, type RoutePoint } from "./RunMap3D.tsx";

type SegmentLike = { kind: string };
type RouteShape = "track" | "loop" | "outback";

function hashSeed(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function inferShape(structure: readonly SegmentLike[] | undefined, distanceKm: number | null): RouteShape {
  if (structure?.some((s) => s.kind === "interval")) return "track";
  if ((distanceKm ?? 0) >= 14) return "loop";
  if (structure?.some((s) => s.kind === "work")) return "outback";
  return "loop";
}

function buildRoutePath(shape: RouteShape, seed: number): {
  d: string;
  start: [number, number];
  end: [number, number];
} {
  const jx = ((seed % 11) - 5) * 1.8;
  const jy = (((seed >> 4) % 11) - 5) * 1.4;

  if (shape === "track") {
    return {
      d: "M 70 46 L 190 46 A 34 34 0 0 1 190 114 L 70 114 A 34 34 0 0 1 70 46 Z",
      start: [70, 114],
      end: [190, 114],
    };
  }

  if (shape === "outback") {
    const p1x = 46 + jx;
    const p1y = 118 + jy * 0.4;
    const p2x = 112 - jx * 0.6;
    const p2y = 78 + jy;
    const p3x = 178 + jx * 0.7;
    const p3y = 54 - jy * 0.6;
    const p4x = 224 + jx * 0.4;
    const p4y = 34 + jy * 0.5;
    return {
      d: `M ${p1x} ${p1y} Q ${(p1x + p2x) / 2 - 12} ${p1y - 24} ${p2x} ${p2y} T ${p3x} ${p3y} Q ${p3x + 28} ${p3y - 12} ${p4x} ${p4y}`,
      start: [p1x, p1y],
      end: [p4x, p4y],
    };
  }

  // Organic riverfront / park loop
  const sx = 64 + jx * 0.6;
  const sy = 116 + jy * 0.4;
  return {
    d: `M ${sx} ${sy} C ${sx - 28} ${sy - 36}, ${sx + 18} ${38 + jy}, ${126 + jx} ${34 + jy * 0.5} C ${190 + jx} ${30 - jy}, ${228} ${72 + jy}, ${204 - jx * 0.5} ${108} C ${176} ${132}, ${114} ${128 + jy * 0.4}, ${sx + 10} ${sy + 2}`,
    start: [sx, sy],
    end: [sx + 10, sy + 2],
  };
}

/** Strava-inspired route trace card or Garmin-style hero background silhouette. */
export function RoutePreview({
  seedId,
  structure,
  distanceKm,
  elevationGainM,
  locale,
  variant = "card",
  routePoints,
}: {
  seedId: string;
  structure?: readonly SegmentLike[];
  distanceKm: number | null;
  elevationGainM?: number;
  locale: "zh-TW" | "en";
  variant?: "card" | "watermark";
  routePoints?: RoutePoint[] | null;
}) {
  const en = locale === "en";
  const shape = inferShape(structure, distanceKm);

  if (variant === "watermark") {
    const { d } = buildRoutePath(shape, hashSeed(seedId));
    return (
      <svg
        className="ath-hero-route-wm"
        viewBox="0 0 260 150"
        fill="none"
        aria-hidden="true"
      >
        <path d={d} className="ath-hero-route-wm-path" />
      </svg>
    );
  }

  void en;

  return (
    <div className="route-preview-card">
      <RunMap3D
        routePoints={routePoints}
        shape={shape}
        distanceKm={distanceKm}
        elevationGainM={elevationGainM}
        locale={locale}
        height={240}
      />
    </div>
  );
}
