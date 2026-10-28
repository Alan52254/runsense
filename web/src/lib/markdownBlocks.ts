export type BlockType =
  | { type: "header"; level: number; text: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "list"; ordered: boolean; start: number; items: string[] }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "paragraph"; text: string };

const BULLET = /^[-*]\s+/;
const ORDERED = /^(\d{1,3})[.)]\s+/;

function listKind(trimmed: string): "bullet" | "ordered" | null {
  if (BULLET.test(trimmed)) return "bullet";
  return ORDERED.test(trimmed) ? "ordered" : null;
}

/** An answer's text as blocks: the pure half of the markdown renderer. */
export function parseMarkdownBlocks(rawText: string): BlockType[] {
  const lines = rawText.split("\n");
  const blocks: BlockType[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Horizontal Rule
    if (trimmed === "---" || trimmed === "***" || trimmed === "___") {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Headers
    if (trimmed.startsWith("### ")) {
      blocks.push({ type: "header", level: 3, text: trimmed.replace("### ", "") });
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      blocks.push({ type: "header", level: 2, text: trimmed.replace("## ", "") });
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      blocks.push({ type: "header", level: 1, text: trimmed.replace("# ", "") });
      i++;
      continue;
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      blocks.push({ type: "quote", text: trimmed.replace(/^>\s*/, "") });
      i++;
      continue;
    }

    // Table detection: line contains | and next line contains |---
    if (trimmed.startsWith("|") && i + 1 < lines.length && lines[i + 1].includes("|---")) {
      const headers = trimmed
        .split("|")
        .map((s) => s.trim())
        .filter(Boolean);
      i += 2; // skip header and delimiter
      const rows: string[][] = [];

      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const rowCells = lines[i]
          .split("|")
          .map((s) => s.trim())
          .filter((_, idx, arr) => (idx > 0 && idx < arr.length - 1) || arr.length <= 2);
        if (rowCells.length > 0) {
          rows.push(rowCells);
        }
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Lists: bulleted (- or *) or numbered (1. or 1)); a blank line between
    // two items of the same kind does not end the list
    const kind = listKind(trimmed);
    if (kind) {
      const items: string[] = [];
      const start = kind === "ordered" ? Number(trimmed.match(ORDERED)![1]) : 1;
      while (i < lines.length) {
        let at = i;
        while (at < lines.length && !lines[at].trim()) at++;
        const next = at < lines.length ? lines[at].trim() : "";
        if (at >= lines.length || listKind(next) !== kind) break;
        items.push(next.replace(kind === "ordered" ? ORDERED : BULLET, ""));
        i = at + 1;
      }
      blocks.push({ type: "list", ordered: kind === "ordered", start, items });
      continue;
    }

    // Regular Paragraph or Numbered Item
    blocks.push({ type: "paragraph", text: trimmed });
    i++;
  }

  return blocks;
}

