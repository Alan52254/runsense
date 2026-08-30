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
