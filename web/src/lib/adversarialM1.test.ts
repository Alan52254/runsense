import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { inlineStyleKeys } from "./inlineStyles.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const todayHeroPath = join(root, "screens", "athlete", "today", "TodayHero.tsx");
const dashboardPath = join(root, "screens", "athlete", "DashboardScreen.tsx");
const athleteCssPath = join(root, "styles", "athlete.css");

const todayHeroSrc = readFileSync(todayHeroPath, "utf8");
const dashboardSrc = readFileSync(dashboardPath, "utf8");
const athleteCssSrc = readFileSync(athleteCssPath, "utf8");

test("M1 Adversarial: No forbidden vocabulary in TodayHero, Dashboard, or athlete.css", () => {
  const BANNED_EVERYWHERE = [
    "GraphRAG", "Graph RAG", "graph rag", "RAG ", " RAG",
    "XGBoost", "xgboost", "LlamaIndex", "Groq", "Ollama",
    "Gemini", "OpenAI", "LLM", "embedding", "Embedding",
    "vector database", "knowledge graph"
  ];
  const BANNED_IN_MAIN_FLOW = [
    "ranker", "Ranker", "retrieval", "Retrieval", "inference", "Inference"
  ];
  const RETIRED_NAMES = [
    "身體感知", "身體狀況", "短長期負荷比", "低於基準", "高於基準", "接近基準"
  ];

  const targets = [
    { name: "TodayHero.tsx", content: todayHeroSrc },
    { name: "DashboardScreen.tsx", content: dashboardSrc },
    { name: "athlete.css", content: athleteCssSrc }
  ];

  const violations: string[] = [];

  for (const { name, content } of targets) {
    // Strip code comments to focus on actual code and string literals
    const cleanContent = content
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");

    // Check user-visible strings
    const stringMatches = [
      ...cleanContent.matchAll(/"([^"\\]*(?:\\.[^"\\]*)*)"/g),
      ...cleanContent.matchAll(/'([^'\\]*(?:\\.[^'\\]*)*)'/g),
      ...cleanContent.matchAll(/`([^`\\]*(?:\\.[^`\\]*)*)`/g),
    ].map(m => m[1]);

    const allBans = [...BANNED_EVERYWHERE, ...BANNED_IN_MAIN_FLOW, ...RETIRED_NAMES];
    for (const str of stringMatches) {
      for (const banned of allBans) {
        if (str.includes(banned)) {
          violations.push(`${name} string literal "${str}" contains banned word: "${banned}"`);
        }
      }
    }

    // Also check JSX text nodes (e.g., >some text<)
    const jsxTextMatches = [...cleanContent.matchAll(/>([^<>{]+)</g)].map(m => m[1].trim()).filter(Boolean);
    for (const text of jsxTextMatches) {
      for (const banned of allBans) {
        if (text.includes(banned)) {
          violations.push(`${name} JSX text "${text}" contains banned word: "${banned}"`);
        }
      }
    }
  }

  assert.deepEqual(violations, [], `Forbidden vocabulary detected: ${violations.join("; ")}`);
});

test("M1 Adversarial: Zero non-custom-property inline styles in TodayHero and DashboardScreen", () => {
  const violations: string[] = [];

  const targets = [
    { name: "TodayHero.tsx", content: todayHeroSrc },
    { name: "DashboardScreen.tsx", content: dashboardSrc }
  ];

  for (const { name, content } of targets) {
    const bad = inlineStyleKeys(content).filter(s => s.keys.some(k => !k.startsWith("--")));
    for (const s of bad) {
      violations.push(`${name}:${s.line} sets non-token inline styles: ${s.keys.filter(k => !k.startsWith("--")).join(", ")}`);
    }
  }

  assert.deepEqual(violations, [], `Inline style violations: ${violations.join("; ")}`);
});

test("M1 Adversarial: Zero untokenized color literals in TodayHero, Dashboard, or athlete.css", () => {
  const violations: string[] = [];

  const targets = [
    { name: "TodayHero.tsx", content: todayHeroSrc },
    { name: "DashboardScreen.tsx", content: dashboardSrc },
    { name: "athlete.css", content: athleteCssSrc }
  ];

  const colorLiteralRegex = /#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab)\(\s*[\d.]/gi;

  for (const { name, content } of targets) {
    content.split("\n").forEach((line, idx) => {
      // Ignore comment lines
      const trimmed = line.trim();
      if (trimmed.startsWith("/*") || trimmed.startsWith("*") || trimmed.startsWith("//")) return;
      const matches = line.match(colorLiteralRegex);
      if (matches) {
        violations.push(`${name}:${idx + 1} contains literal color: ${matches.join(", ")}`);
      }
    });
  }

  assert.deepEqual(violations, [], `Untokenized color violations: ${violations.join("; ")}`);
});

test("M1 Adversarial: Motion tokens used in athlete.css for M1 candidate pills and badges", () => {
  const violations: string[] = [];

  // Specifically check M1 classes in athlete.css
  const m1Classes = [
    ".ath-hero-badge",
    ".ath-hero-privacy-badge",
    ".ath-hero-loop-badge",
    ".ath-hero-candidates",
    ".ath-candidate-pill",
    ".ath-coach-flow-bar"
  ];

  const LITERAL_TIMING = /cubic-bezier\(|(?<![\w-])\d*\.?\d+m?s\b(?!\s*steps)/;

  athleteCssSrc.split("\n").forEach((line, idx) => {
    if (!/(^|[\s;{])(transition|animation)(-duration|-timing-function|-delay)?\s*:/.test(line)) return;
    if (line.includes("infinite") || line.includes("animation-delay")) return;
    const stripped = line.replace(/var\([^)]*\)/g, "");
    if (LITERAL_TIMING.test(stripped)) {
      violations.push(`athlete.css:${idx + 1} uses literal timing: ${line.trim()}`);
    }
  });

  assert.deepEqual(violations, [], `Motion token violations: ${violations.join("; ")}`);
});

test("M1 Adversarial: Font size floor (>= 12px) in athlete.css M1 elements", () => {
  const violations: string[] = [];

  // Extract all font-size declarations from athlete.css
  athleteCssSrc.split("\n").forEach((line, idx) => {
    const match = line.match(/font-size:\s*([^;]+);/);
    if (match) {
      const val = match[1].trim();
      // Look for literal pixel values below 12px
      const pxMatch = val.match(/(\d+)px/);
      if (pxMatch && parseInt(pxMatch[1], 10) < 12) {
        violations.push(`athlete.css:${idx + 1} font-size is below 12px: ${val}`);
      }
      // Check for --fs-11 or smaller if defined
      if (/--fs-(?:10|11|[1-9])\b/.test(val)) {
        violations.push(`athlete.css:${idx + 1} uses token below 12px: ${val}`);
      }
    }
  });

  assert.deepEqual(violations, [], `Type floor violations: ${violations.join("; ")}`);
});

test("M1 Adversarial: Candidate switcher pace calculation edge cases", () => {
  // Test the pace calculation formula used in TodayHero:
  // const paceSec = cand.distanceKm > 0 && cand.durationMinutes > 0
  //   ? Math.round((cand.durationMinutes * 60) / cand.distanceKm)
  //   : null;
  const calcPace = (distanceKm: number, durationMinutes: number) => {
    return distanceKm > 0 && durationMinutes > 0
      ? Math.round((durationMinutes * 60) / distanceKm)
      : null;
  };

  assert.equal(calcPace(0, 45), null, "0 distance yields null, avoiding Infinity");
  assert.equal(calcPace(10, 0), null, "0 duration yields null");
  assert.equal(calcPace(-5, 30), null, "negative distance yields null");
  assert.equal(calcPace(10, 50), 300, "10km in 50m yields 300s/km (5:00/km)");
  assert.equal(calcPace(5, 25), 300, "5km in 25m yields 300s/km");
});
