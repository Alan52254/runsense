import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const styles = join(dirname(fileURLToPath(import.meta.url)), "..", "styles");
const read = (name: string) => readFileSync(join(styles, name), "utf8");

test("figure units never render under the 12px floor", () => {
  const unit = read("figure.css").match(/\.rs-figure__unit\s*\{([^}]*)\}/)?.[1] ?? "";
  assert.match(unit, /font-size:\s*max\(var\(--fs-12\),/);
});

test("tokens.css defines each custom property once per scope", () => {
  const seen = new Map<string, number>();
  const stack: string[] = [];
  const dupes: string[] = [];
  for (const raw of read("tokens.css").split("\n")) {
    const line = raw.replace(/\/\*.*?\*\//g, "");
    if (line.includes("{") && !line.includes("}")) {
      stack.push(line.split("{")[0].trim());
      continue;
    }
    const name = line.match(/^\s*(--[\w-]+)\s*:/)?.[1];
    if (name) {
      const key = `${stack.join(" > ")} ${name}`;
      if (seen.has(key)) dupes.push(key);
      seen.set(key, 1);
    }
    if (line.includes("}") && !line.includes("{")) stack.pop();
  }
  assert.deepEqual(dupes, []);
});
