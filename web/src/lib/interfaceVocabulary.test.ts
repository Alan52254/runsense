/** The interface speaks to the Athlete, never about itself.
 *
 *  Retrieval, provider, and architecture vocabulary means nothing to a runner
 *  and makes the product talk about its own plumbing. This test fails if any
 *  of it reappears in a user-visible string.
 *
 *  Scope: everything the Athlete reads in the ordinary flow. The methodology
 *  screen is the deliberate "how this works" layer -- it keeps substance like
 *  ranking, confidence, and abstention, and is exempt from the words that
 *  describe *how* those are computed, but never from provider or acronym
 *  vocabulary, which is checked everywhere.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Banned everywhere, including the methodology screen: these name a vendor,
 *  a library, or an acronym an Athlete has no reason to know. */
const BANNED_EVERYWHERE = [
  "GraphRAG",
  "Graph RAG",
  "graph rag",
  "RAG ",
  " RAG",
  "XGBoost",
  "xgboost",
  "LlamaIndex",
  "Groq",
  "Ollama",
  "Gemini",
  "OpenAI",
  "LLM",
  "embedding",
  "Embedding",
  "vector database",
  "knowledge graph",
];

/** Allowed on screen since the v2 brief (2026-10-22): the product names its
 *  coach model and its load and safety terms plainly. Kept here so a later
 *  edit to the bans cannot quietly forbid them again. */
const ALLOWED_TECHNICAL_WORDS = ["AI", "AI 健康教練", "Llama", "Llama 3.1", "ACWR", "Triage"];

/** Also banned in the ordinary flow, where an Athlete is trying to train
 *  rather than to understand the system. */
const BANNED_IN_MAIN_FLOW = [
  "ranker",
  "Ranker",
  "retrieval",
  "Retrieval",
  "inference",
  "Inference",
];

const METHODOLOGY_SCREEN = join("screens", "athlete", "MethodScreen.tsx");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    if (!/\.(ts|tsx)$/.test(entry) || entry.endsWith(".test.ts")) return [];
    return [full];
  });
}

/** Only the strings an Athlete can actually read: string and template
 *  literals, with comments stripped so an explanatory note about the
 *  architecture is not mistaken for interface copy. */
function userVisibleStrings(source: string): string[] {
  const withoutComments = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

  return [
    ...withoutComments.matchAll(/"([^"\\]*(?:\\.[^"\\]*)*)"/g),
    ...withoutComments.matchAll(/'([^'\\]*(?:\\.[^'\\]*)*)'/g),
    ...withoutComments.matchAll(/`([^`\\]*(?:\\.[^`\\]*)*)`/g),
  ]
    .map((match) => match[1])
    // Import paths, CSS values, and API routes are not read by anyone.
    .filter((value) => !value.startsWith("."))
    .filter((value) => !value.startsWith("/"))
    .filter((value) => !/^[a-z-]+$/.test(value));
}

test("no user-visible string names a vendor, library, or acronym", () => {
  const offences: string[] = [];

  for (const file of sourceFiles(SRC)) {
    for (const value of userVisibleStrings(readFileSync(file, "utf8"))) {
      for (const banned of BANNED_EVERYWHERE) {
        if (value.includes(banned)) {
          offences.push(`${file}: "${value.slice(0, 90)}" contains ${banned.trim()}`);
        }
      }
    }
  }

  assert.deepEqual(offences, []);
});

test("the ordinary flow does not describe how results are computed", () => {
  const offences: string[] = [];

  for (const file of sourceFiles(SRC)) {
    if (file.endsWith(METHODOLOGY_SCREEN)) continue;
    for (const value of userVisibleStrings(readFileSync(file, "utf8"))) {
      for (const banned of BANNED_IN_MAIN_FLOW) {
        if (value.includes(banned)) {
          offences.push(`${file}: "${value.slice(0, 90)}" contains ${banned}`);
        }
      }
    }
  }

  assert.deepEqual(offences, []);
});

test("the v2 technical words stay allowed", () => {
  const bans = [...BANNED_EVERYWHERE, ...BANNED_IN_MAIN_FLOW];
  const blocked = ALLOWED_TECHNICAL_WORDS.filter((word) =>
    bans.some((banned) => word.includes(banned)),
  );
  assert.deepEqual(blocked, []);
});

/** One name per feature (2026-10-23): the body feature is 身體回報 and the
 *  load ratio is ACWR 負荷比, with the zone words from lib/acwr.ts. */
const RETIRED_NAMES = ["身體感知", "身體狀況", "短長期負荷比", "低於基準", "高於基準", "接近基準"];

test("retired feature names do not come back", () => {
  const offences: string[] = [];
  for (const file of sourceFiles(SRC)) {
    for (const value of userVisibleStrings(readFileSync(file, "utf8"))) {
      for (const name of RETIRED_NAMES) {
        if (value.includes(name)) offences.push(`${file}: "${value.slice(0, 90)}" contains ${name}`);
      }
    }
  }
  assert.deepEqual(offences, []);
});
