import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

/** Compact GPS point: [lon, lat, elevationM?, speedMps?, hrBpm?] */
export type RoutePoint = [
  number,
  number,
  number | null | undefined,
  number | null | undefined,
  number | null | undefined,
];

type ColorMode = "pace" | "hr" | "gradient";
type RouteShape = "track" | "loop" | "outback";

interface RunMap3DProps {
  routePoints?: RoutePoint[] | null;
  shape?: RouteShape;
  distanceKm?: number | null;
  elevationGainM?: number;
  locale: "zh-TW" | "en";
  isLive?: boolean;
  height?: number;
}

interface LineFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: {
      type: "LineString";
      coordinates: Array<[number, number]>;
    };
    properties: {
      pace: number;
      hr: number;
      gradient: number;
    };
  }>;
}

const TAIPEI_LOOP_DEMO: RoutePoint[] = [
  [121.5318, 25.0742, 6.2, 3.15, 142],
  [121.5346, 25.0751, 6.5, 3.28, 146],
  [121.5379, 25.0758, 7.1, 3.35, 149],
  [121.5416, 25.0761, 8.4, 3.42, 152],
  [121.5453, 25.0757, 9.8, 3.38, 154],
  [121.5488, 25.0745, 8.2, 3.51, 156],
  [121.5515, 25.0728, 6.9, 3.62, 158],
  [121.5498, 25.0713, 6.4, 3.45, 155],
  [121.5461, 25.0715, 6.1, 3.34, 151],
  [121.5422, 25.0721, 5.9, 3.29, 148],
  [121.5381, 25.0725, 6.0, 3.32, 147],
  [121.5342, 25.0731, 6.1, 3.41, 149],
  [121.5319, 25.0741, 6.2, 3.55, 153],
];

const TAIPEI_TRACK_DEMO: RoutePoint[] = [
  [121.5499, 25.0504, 12.0, 4.15, 156],
  [121.5508, 25.0504, 12.1, 4.35, 164],
  [121.5513, 25.0508, 12.1, 4.42, 169],
  [121.5512, 25.0513, 12.0, 4.25, 166],
  [121.5504, 25.0515, 12.0, 3.65, 152],
  [121.5496, 25.0513, 12.0, 3.85, 155],
  [121.5493, 25.0508, 12.0, 4.30, 165],
  [121.5498, 25.0504, 12.0, 4.48, 171],
];

const TAIPEI_OUTBACK_DEMO: RoutePoint[] = [
  [121.5228, 25.0764, 5.8, 3.25, 141],
  [121.5262, 25.0772, 6.4, 3.42, 147],
  [121.5299, 25.0778, 7.6, 3.58, 153],
  [121.5335, 25.0785, 9.2, 3.66, 157],
  [121.5374, 25.0789, 11.4, 3.74, 161],
  [121.5411, 25.0792, 13.8, 3.62, 163],
  [121.5375, 25.0787, 11.2, 3.79, 160],
  [121.5336, 25.0783, 9.0, 3.82, 158],
  [121.5298, 25.0776, 7.4, 3.75, 155],
  [121.5261, 25.0770, 6.3, 3.68, 152],
  [121.5230, 25.0763, 5.8, 3.71, 151],
];

function haversineMeters(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function applyPrivacyTrim(points: RoutePoint[], trimMeters = 200): RoutePoint[] {
  if (points.length < 6) return points;
  let startIdx = 0;
  let distFromStart = 0;
  while (startIdx < points.length - 3 && distFromStart < trimMeters) {
    distFromStart += haversineMeters(
      points[startIdx][0],
      points[startIdx][1],
      points[startIdx + 1][0],
      points[startIdx + 1][1],
    );
    startIdx += 1;
  }

  let endIdx = points.length - 1;
  let distFromEnd = 0;
  while (endIdx > startIdx + 2 && distFromEnd < trimMeters) {
    distFromEnd += haversineMeters(
      points[endIdx][0],
      points[endIdx][1],
      points[endIdx - 1][0],
      points[endIdx - 1][1],
    );
    endIdx -= 1;
  }

  return points.slice(startIdx, endIdx + 1);
}

function buildSegmentsGeoJson(points: RoutePoint[]): LineFeatureCollection {
  const features: LineFeatureCollection["features"] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const distM = Math.max(1, haversineMeters(p1[0], p1[1], p2[0], p2[1]));
    const ele1 = p1[2] ?? 0;
    const ele2 = p2[2] ?? 0;
    const gradient = Math.max(-15, Math.min(15, ((ele2 - ele1) / distM) * 100));
    const speedMps = p2[3] ?? p1[3] ?? 3.2;
    const paceMinPerKm = speedMps > 0.5 ? Math.min(10, Math.max(2.5, 1000 / speedMps / 60)) : 5.5;
    const hr = p2[4] ?? p1[4] ?? 148;

    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [p1[0], p1[1]],
          [p2[0], p2[1]],
        ],
      },
      properties: {
        pace: Number(paceMinPerKm.toFixed(2)),
        hr: Number(hr),
        gradient: Number(gradient.toFixed(2)),
      },
    });
  }
  return { type: "FeatureCollection", features };
}

function readPalette(shell: HTMLElement | null) {
  const cs = shell ? getComputedStyle(shell) : null;
  const pick = (name: string, fallback: string) => cs?.getPropertyValue(name).trim() || fallback;
  return {
    fast: pick("--map-c-fast", "orange"),
    mid: pick("--map-c-mid", "gold"),
    steady: pick("--map-c-steady", "limegreen"),
    easy: pick("--map-c-easy", "deepskyblue"),
    hot: pick("--map-c-hot", "red"),
  };
}

function lineColorExpression(
  mode: ColorMode,
  palette: ReturnType<typeof readPalette>,
): maplibregl.ExpressionSpecification {
  if (mode === "hr") {
    return [
      "interpolate",
      ["linear"],
      ["get", "hr"],
      125, palette.easy,
      145, palette.steady,
      160, palette.mid,
      178, palette.hot,
    ];
  }
  if (mode === "gradient") {
    return [
      "interpolate",
      ["linear"],
      ["get", "gradient"],
      -6, palette.easy,
      0, palette.mid,
      6, palette.hot,
    ];
  }
  return [
    "interpolate",
    ["linear"],
    ["get", "pace"],
    3.6, palette.fast,
    4.6, palette.mid,
    5.5, palette.steady,
    6.8, palette.easy,
  ];
}

export function RunMap3D({
  routePoints,
  shape = "loop",
  distanceKm,
  elevationGainM,
  locale,
  isLive = false,
  height = 240,
}: RunMap3DProps) {
  const en = locale === "en";
  const shellRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [colorMode, setColorMode] = useState<ColorMode>("pace");
  const [is3D, setIs3D] = useState(true);
  const [privacyMask, setPrivacyMask] = useState(true);
  const [mapFailed, setMapFailed] = useState(false);

  const hasRealRoute = Array.isArray(routePoints) && routePoints.length >= 2;
  const rawPoints = useMemo(() => {
    if (hasRealRoute && routePoints) return routePoints;
    if (shape === "track") return TAIPEI_TRACK_DEMO;
    if (shape === "outback") return TAIPEI_OUTBACK_DEMO;
    return TAIPEI_LOOP_DEMO;
  }, [hasRealRoute, routePoints, shape]);

  const activePoints = useMemo(
    () => (hasRealRoute && privacyMask && !isLive ? applyPrivacyTrim(rawPoints, 200) : rawPoints),
    [hasRealRoute, privacyMask, isLive, rawPoints],
  );

  const geojson = useMemo(() => buildSegmentsGeoJson(activePoints), [activePoints]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let map: maplibregl.Map;
    const palette = readPalette(shellRef.current);
    try {
      const first = activePoints[0] ?? [121.54, 25.074];
      map = new maplibregl.Map({
        container: el,
        center: [first[0], first[1]],
        zoom: 14.3,
        pitch: is3D ? 56 : 0,
        bearing: -18,
        attributionControl: false,
        style: {
          version: 8,
          sources: {
            "dark-basemap": {
              type: "raster",
              // TODO: 之後補上 MapTiler / Carto / Google Maps 3D API Key（可透過 VITE_MAP_TILE_URL 設定）
              // CartoDB dark_all 目前會顯示 "API KEY REQUIRED" 浮水印，暫以 OSM 暗色濾鏡作為免費免 Key 底圖
              tiles: [
                import.meta.env.VITE_MAP_TILE_URL ||
                  "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
              ],
              tileSize: 256,
              maxzoom: 19,
            },
            "terrain-dem": {
              type: "raster-dem",
              tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
              encoding: "terrarium",
              tileSize: 256,
              maxzoom: 15,
            },
          },
          layers: [
            {
              id: "dark-basemap-layer",
              type: "raster",
              source: "dark-basemap",
              paint: import.meta.env.VITE_MAP_TILE_URL
                ? {
                    "raster-brightness-max": 0.92,
                    "raster-contrast": 0.12,
                  }
                : {
                    "raster-saturation": -0.8,
                    "raster-brightness-max": 0.42,
                    "raster-contrast": 0.25,
                  },
            },
          ],
          terrain: {
            source: "terrain-dem",
            exaggeration: 1.35,
          },
        },
      });
    } catch {
      setMapFailed(true);
      return;
    }

    mapRef.current = map;

    map.on("load", () => {
      map.addSource("run-route", {
        type: "geojson",
        data: geojson as unknown as maplibregl.GeoJSONSourceSpecification["data"],
      });

      map.addLayer({
        id: "run-route-glow",
        type: "line",
        source: "run-route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": 10,
          "line-opacity": 0.24,
          "line-color": lineColorExpression(colorMode, palette),
        },
      });

      map.addLayer({
        id: "run-route-core",
        type: "line",
        source: "run-route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": 4.2,
          "line-color": lineColorExpression(colorMode, palette),
        },
      });

      if (activePoints.length >= 2) {
        const bounds = new maplibregl.LngLatBounds();
        for (const pt of activePoints) bounds.extend([pt[0], pt[1]]);
        map.fitBounds(bounds, {
          padding: 36,
          pitch: is3D ? 56 : 0,
          bearing: -18,
          duration: 500,
        });
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const src = map.getSource("run-route") as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData(geojson as unknown as Parameters<maplibregl.GeoJSONSource["setData"]>[0]);
    }
    if (activePoints.length >= 2) {
      const bounds = new maplibregl.LngLatBounds();
      for (const pt of activePoints) bounds.extend([pt[0], pt[1]]);
      map.fitBounds(bounds, { padding: 36, duration: 400 });
    }
  }, [geojson, activePoints]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const expr = lineColorExpression(colorMode, readPalette(shellRef.current));
    if (map.getLayer("run-route-core")) map.setPaintProperty("run-route-core", "line-color", expr);
    if (map.getLayer("run-route-glow")) map.setPaintProperty("run-route-glow", "line-color", expr);
  }, [colorMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.easeTo({ pitch: is3D ? 56 : 0, duration: 350 });
  }, [is3D]);

  const demoPlaceLabel =
    shape === "track"
      ? (en ? "Demo · Taipei Track" : "示範路線 · 臺北田徑場")
      : (en ? "Demo · Dajia Riverside" : "示範路線 · 臺北大佳河濱");

  const shellVars = { "--map-height": `${height}px` } as CSSProperties;

  return (
    <div ref={shellRef} className="run-map-3d-shell" style={shellVars}>
      <div className="run-map-3d-overlay">
        <div className="run-map-3d-badge">
          <span className={`run-map-3d-dot ${isLive ? "is-live" : hasRealRoute ? "is-fit" : ""}`} />
          <span>
            {isLive
              ? (en ? "Live GPS" : "即時 GPS 定位")
              : hasRealRoute
                ? (en ? "FIT GPS 3D Route" : "實測 FIT 3D 路線")
                : demoPlaceLabel}
          </span>
          {distanceKm ? <span className="run-map-3d-meta">· {distanceKm.toFixed(1)} km</span> : null}
          {elevationGainM ? <span className="run-map-3d-meta">· +{Math.round(elevationGainM)} m</span> : null}
        </div>

        <div className="run-map-3d-controls">
          {(["pace", "hr", "gradient"] as ColorMode[]).map((m) => {
            const active = colorMode === m;
            const label =
              m === "pace"
                ? (en ? "Pace" : "配速")
                : m === "hr"
                  ? (en ? "HR" : "心率")
                  : (en ? "Grade" : "坡度");
            return (
              <button
                key={m}
                type="button"
                className={`run-map-3d-btn ${active ? "is-active" : ""}`}
                onClick={() => setColorMode(m)}
              >
                {label}
              </button>
            );
          })}
          <button
            type="button"
            className="run-map-3d-btn"
            onClick={() => setIs3D((v) => !v)}
          >
            {is3D ? "3D" : "2D"}
          </button>
          {hasRealRoute && !isLive && (
            <button
              type="button"
              className={`run-map-3d-btn ${privacyMask ? "is-privacy" : ""}`}
              title={en ? "Hide first/last 200m around home" : "遮罩起終點 200m 隱私區"}
              onClick={() => setPrivacyMask((v) => !v)}
            >
              {en ? "Privacy" : "隱私遮罩"}
            </button>
          )}
        </div>
      </div>

      {mapFailed ? (
        <div className="run-map-3d-fallback">
          {en ? "WebGL 3D map unavailable in this browser." : "此瀏覽器環境暫不支援 WebGL 3D 地圖"}
        </div>
      ) : (
        <div ref={containerRef} className="run-map-3d-canvas" />
      )}
    </div>
  );
}
