import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { inlineStyleKeys } from "./inlineStyles.ts";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sources(path) : [path];
  });
}

/**
 * Files not yet moved onto Row/Stack/Cluster/Text. Each needs a reason; shrink it, never grow it.
 * Everything on the demo path is already clean and must stay that way.
 */
export const INLINE_STYLE_ALLOW_LIST: Record<string, string> = {
  "app/AppShell.tsx": "shell chrome: rail, bottom bar and ticker positioning; next ticket moves it to layout.css",
  "components/charts.tsx": "chart coordinates, tooltip position and series fills; need --x/--y/--series custom properties",
  "components/ConditionsExplorer.tsx": "legacy drawer explorer built from inline layout; not on the main demo path",
  "components/motion.tsx": "framer-motion tilt/transform values; need motion-value to custom property bridge",
  "components/ui.tsx": "shared Field/Segmented/Modal internals with width and flex tweaks",
  "components/workoutBuilder.tsx": "coach workout builder form layout",
  "components/workoutPrescription.tsx": "prescription card layout",
  "screens/LoginScreen.tsx": "login form layout",
  "screens/athlete/LiveRunScreen.tsx": "live run telemetry layout (largest remaining file)",
  "screens/athlete/MethodScreen.tsx": "method explainer prose layout",
  "screens/athlete/TeamScreen.tsx": "athlete team page layout",
  "screens/athlete/TrainingLoadScreen.tsx": "training load page layout",
  "screens/athlete/settings/PrivacySettings.tsx": "settings page layout",
  "screens/athlete/settings/SecuritySettings.tsx": "settings page layout",
  "screens/coach/AssignmentsScreen.tsx": "coach assignments page layout",
  "screens/coach/AthleteDetailScreen.tsx": "coach athlete detail layout",
};

test("inlineStyleKeys reads the property names of each style literal", () => {
  const src = `<a style={{ gap: 8, color: cond ? "a,b" : "c" }}/>\n<b style={{ "--x": \`\${n}px\`, ...rest }}/>`;
  assert.deepEqual(inlineStyleKeys(src), [
    { line: 1, keys: ["gap", "color"] },
    { line: 2, keys: ["--x", "..."] },
  ]);
});

test("style={{}} may only set CSS custom properties outside the allow-list", () => {
  const violations: string[] = [];
  const stale = new Set(Object.keys(INLINE_STYLE_ALLOW_LIST));
  for (const file of sources(sourceRoot)) {
    if (extname(file) !== ".tsx") continue;
    const name = relative(sourceRoot, file).replaceAll("\\", "/");
    const bad = inlineStyleKeys(readFileSync(file, "utf8")).filter(s => s.keys.some(k => !k.startsWith("--")));
    if (name in INLINE_STYLE_ALLOW_LIST) { if (bad.length) stale.delete(name); continue; }
    for (const s of bad) violations.push(`${name}:${s.line} sets ${s.keys.filter(k => !k.startsWith("--")).join(", ")}`);
  }
  assert.deepEqual(violations, [], "Use Row/Stack/Cluster/Text or a class; pass dynamic values as --custom-properties.");
  assert.deepEqual([...stale], [], "Remove clean files from INLINE_STYLE_ALLOW_LIST.");
});
