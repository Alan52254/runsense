import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { BRAND_PX, brandFiles, legibleVariant } from "./brandMark.ts";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sources(path) : [path];
  });
}

test("sizes step up and the tile gives way to the runner below 36px", () => {
  assert.deepEqual(Object.values(BRAND_PX), [28, 36, 64, 96]);
  assert.equal(legibleVariant("mark", "sm"), "runner");
  assert.equal(legibleVariant("mark", "md"), "mark");
  assert.equal(legibleVariant("runner", "sm"), "runner");
});

test("small runners use the thickened raster, large ones the 192px one", () => {
  assert.equal(brandFiles("runner", "sm").x1, "runner-72");
  assert.equal(brandFiles("runner", "md").x2, "runner-72");
  assert.equal(brandFiles("runner", "lg").x1, "runner-192");
  assert.deepEqual(brandFiles("mark", "xl"), { x1: "mark-96", x2: "mark-192" });
});

test("only BrandMark touches the logo files, and the old logo markup is gone", () => {
  const violations: string[] = [];
  for (const file of sources(sourceRoot)) {
    const name = relative(sourceRoot, file).replaceAll("\\", "/");
    if (![".ts", ".tsx", ".css"].includes(extname(file)) || file.endsWith(".test.ts")) continue;
    if (name === "components/BrandMark.tsx" || name === "lib/brandMark.ts") continue;
    const text = readFileSync(file, "utf8");
    if (/assets\/brand/.test(text)) violations.push(`${name} imports the logo files`);
    if (/brand-led|\bbrand-mark\b/.test(text)) violations.push(`${name} has the old logo markup`);
    if (/PersonSimpleRun/.test(text) && name !== "components/Icon.tsx") violations.push(`${name} draws its own runner`);
    if (/name="runner"/.test(text) && /brand|logo/i.test(text.split("\n").filter(l => /name="runner"/.test(l)).join(""))) violations.push(`${name} uses the runner icon as a logo`);
  }
  assert.deepEqual(violations, []);
});

test("the shell and login show the logo through BrandMark", () => {
  for (const name of ["app/AppShell.tsx", "screens/LoginScreen.tsx", "components/CoachAvatar.tsx"]) {
    assert.match(readFileSync(join(sourceRoot, name), "utf8"), /BrandMark/, name);
  }
});
