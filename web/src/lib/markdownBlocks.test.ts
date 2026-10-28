import assert from "node:assert/strict";
import test from "node:test";

import { parseMarkdownBlocks } from "./markdownBlocks.ts";

test("dash and star items become one bulleted list", () => {
  assert.deepEqual(parseMarkdownBlocks("先看負荷：\n- 近 7 天三次\n* 昨天間歇\n- 今天輕鬆跑"), [
    { type: "paragraph", text: "先看負荷：" },
    { type: "list", ordered: false, start: 1, items: ["近 7 天三次", "昨天間歇", "今天輕鬆跑"] },
  ]);
});

test("numbered items become one numbered list that keeps its first number", () => {
  assert.deepEqual(parseMarkdownBlocks("1. 暖身 10 分鐘\n2. 輕鬆跑 30 分鐘\n3) 收操"), [
    { type: "list", ordered: true, start: 1, items: ["暖身 10 分鐘", "輕鬆跑 30 分鐘", "收操"] },
  ]);
  assert.deepEqual(parseMarkdownBlocks("3. 第三\n4. 第四"), [
    { type: "list", ordered: true, start: 3, items: ["第三", "第四"] },
  ]);
});

test("a bulleted and a numbered list next to each other stay two lists", () => {
  const blocks = parseMarkdownBlocks("- a\n- b\n1. c\n2. d");
  assert.deepEqual(blocks.map((b) => b.type === "list" && b.ordered), [false, true]);
});

test("a blank line between numbered items does not split the list", () => {
  assert.deepEqual(parseMarkdownBlocks("1. 甲\n\n2. 乙"), [
    { type: "list", ordered: true, start: 1, items: ["甲", "乙"] },
  ]);
});

test("a number inside a sentence, or without a space after the dot, is not a list", () => {
  assert.deepEqual(parseMarkdownBlocks("2026. 今年"), [{ type: "paragraph", text: "2026. 今年" }]);
  assert.deepEqual(parseMarkdownBlocks("3.5 公里"), [{ type: "paragraph", text: "3.5 公里" }]);
  assert.deepEqual(parseMarkdownBlocks("跑了 3. 次"), [{ type: "paragraph", text: "跑了 3. 次" }]);
});

test("headers, quotes, rules and tables are still read", () => {
  const blocks = parseMarkdownBlocks("## 標題\n> 引言\n---\n| a | b |\n|---|---|\n| 1 | 2 |");
  assert.deepEqual(blocks.map((b) => b.type), ["header", "quote", "hr", "table"]);
});

test("a stream cut mid-list still parses what has arrived", () => {
  assert.deepEqual(parseMarkdownBlocks("1. 暖身\n2."), [
    { type: "list", ordered: true, start: 1, items: ["暖身"] },
    { type: "paragraph", text: "2." },
  ]);
});
