import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sources(path) : [path];
  });
}

test("color literals are defined only in tokens.css, including SVG and motion colors", () => {
  const violations: string[] = [];
  for (const file of sources(sourceRoot)) {
    if (!new Set([".css", ".ts", ".tsx", ".svg"]).has(extname(file)) || file.endsWith(".test.ts")) continue;
    if (relative(sourceRoot, file).replaceAll("\\", "/") === "styles/tokens.css") continue;
    readFileSync(file, "utf8").split("\n").forEach((line, index) => {
      // Match literal channels, not rgb(var(--channels)), selectors or URL fragments.
      const matches = line.match(/#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab)\(\s*[\d.]/gi);
      if (matches) violations.push(`${relative(sourceRoot, file)}:${index + 1} ${matches.join(", ")}`);
    });
  }
  assert.deepEqual(violations, [], "Use a named semantic token for colors; do not add file-wide exceptions.");
});

test("legacy card and glass wrappers cannot reintroduce their own material", () => {
  for (const name of ["components.css", "glass.css", "athlete.css"]) {
    const css = readFileSync(join(sourceRoot, "styles", name), "utf8");
    const declarations = [...css.matchAll(/(?:^|\n)\.(?:card|glass(?:--\w+)?|ath-panel)\s*\{([^}]*)\}/g)];
    for (const [, body] of declarations) {
      assert.doesNotMatch(body, /(?:background|border(?:-radius)?|backdrop-filter|box-shadow|padding)\s*:/, `${name} duplicates Surface material`);
    }
  }
});
