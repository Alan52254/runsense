import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const styles = join(dirname(fileURLToPath(import.meta.url)), "..", "styles");

// Looping indicators (spinners, caret, typing dots, LED, ticker) are not intents:
// their period is part of the drawing, and reduced motion stops them by behaviour.
const LOOP = /\binfinite\b/;
const LITERAL = /cubic-bezier\(|(?<![\w-])\d*\.?\d+m?s\b(?!\s*steps)/;

test("durations and easings come from the motion tokens, not literals", () => {
  const violations: string[] = [];
  for (const name of readdirSync(styles).filter(n => n.endsWith(".css") && n !== "tokens.css")) {
    readFileSync(join(styles, name), "utf8").split("\n").forEach((line, index) => {
      if (!/(^|[\s;{])(transition|animation)(-duration|-timing-function|-delay)?\s*:/.test(line)) return;
      if (LOOP.test(line) || /animation-delay/.test(line)) return;
      if (LITERAL.test(line.replace(/var\([^)]*\)/g, ""))) violations.push(`${relative(styles, join(styles, name))}:${index + 1} ${line.trim()}`);
    });
  }
  assert.deepEqual(violations, [], "Use --motion-press/reveal/slide/emphasis and --ease-* from tokens.css.");
});
