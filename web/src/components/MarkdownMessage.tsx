import React from "react";

interface MarkdownMessageProps {
  content: string;
  isStreaming?: boolean;
}

export function MarkdownMessage({ content, isStreaming }: MarkdownMessageProps) {
  // Parse message into blocks: paragraphs, lists, tables, headers, blockquotes
  const blocks = parseMarkdownBlocks(content);

  return (
    <div className="markdown-render" style={{ fontSize: 13.5, lineHeight: 1.65, color: "inherit" }}>
      {blocks.map((block, index) => (
        <React.Fragment key={index}>{renderBlock(block)}</React.Fragment>
      ))}
      {isStreaming && (
        <span
          style={{
            display: "inline-block",
            width: 8,
            height: 15,
            backgroundColor: "var(--accent)",
            marginLeft: 4,
            verticalAlign: "middle",
            animation: "pulse 0.8s infinite",
          }}
        />
      )}
    </div>
  );
}

type BlockType =
  | { type: "header"; level: number; text: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "list"; items: string[] }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "paragraph"; text: string };

function parseMarkdownBlocks(rawText: string): BlockType[] {
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

    // Unordered List
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].trim().startsWith("- ") || lines[i].trim().startsWith("* "))) {
        items.push(lines[i].trim().replace(/^[-*]\s*/, ""));
        i++;
      }
      blocks.push({ type: "list", items });
      continue;
    }

    // Regular Paragraph or Numbered Item
    blocks.push({ type: "paragraph", text: trimmed });
    i++;
  }

  return blocks;
}

function renderFormattedInline(text: string) {
  const sublines = text.split(/<br\s*\/?>/gi);
  return sublines.map((subline, sIdx) => {
    const parts = subline.split(/(\*\*.*?\*\*|\*.*?\*|`.*?`)/g);
    return (
      <React.Fragment key={sIdx}>
        {sIdx > 0 && <br />}
        {parts.map((part, index) => {
          if (part.startsWith("**") && part.endsWith("**")) {
            return (
              <strong key={index} style={{ color: "var(--accent-ink)", fontWeight: 750 }}>
                {part.slice(2, -2)}
              </strong>
            );
          }
          if (part.startsWith("`") && part.endsWith("`")) {
            return (
              <code
                key={index}
                style={{
                  backgroundColor: "var(--surface-3)",
                  border: "1px solid var(--border)",
                  color: "var(--text-2)",
                  padding: "2px 5px",
                  borderRadius: 4,
                  fontSize: "0.9em",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {part.slice(1, -1)}
              </code>
            );
          }
          return part;
        })}
      </React.Fragment>
    );
  });
}

function renderBlock(block: BlockType) {
  switch (block.type) {
    case "header":
      return (
        <div
          style={{
            fontWeight: 800,
            fontSize: block.level === 1 ? 16 : block.level === 2 ? 14.5 : 13.5,
            color: "var(--text)",
            marginTop: 10,
            marginBottom: 6,
            borderBottom: block.level <= 2 ? "1px solid var(--border)" : "none",
            paddingBottom: block.level <= 2 ? 4 : 0,
          }}
        >
          {renderFormattedInline(block.text)}
        </div>
      );

    case "table":
      return (
        <div
          style={{
            margin: "10px 0",
            overflowX: "auto",
            borderRadius: 8,
            border: "1px solid var(--border)",
            backgroundColor: "var(--surface)",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 12,
              textAlign: "left",
            }}
          >
            <thead>
              <tr style={{ backgroundColor: "var(--accent-soft)", borderBottom: "1px solid var(--border)" }}>
                {block.headers.map((h, idx) => (
                  <th key={idx} style={{ padding: "7px 10px", color: "var(--accent-ink)", fontWeight: 750 }}>
                    {renderFormattedInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rIdx) => (
                <tr
                  key={rIdx}
                  style={{
                    backgroundColor: rIdx % 2 === 0 ? "transparent" : "var(--surface-2)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {row.map((cell, cIdx) => (
                    <td key={cIdx} style={{ padding: "6px 10px", verticalAlign: "top" }}>
                      {renderFormattedInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "list":
      return (
        <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
          {block.items.map((item, idx) => (
            <li key={idx} style={{ marginBottom: 4 }}>
              {renderFormattedInline(item)}
            </li>
          ))}
        </ul>
      );

    case "quote":
      return (
        <div
          style={{
            margin: "8px 0",
            padding: "8px 12px",
            borderLeft: "3px solid var(--accent)",
            backgroundColor: "var(--accent-soft)",
            borderRadius: "0 8px 8px 0",
            fontSize: 12.5,
          }}
        >
          {renderFormattedInline(block.text)}
        </div>
      );

    case "hr":
      return <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "12px 0" }} />;

    case "paragraph":
      return <p style={{ margin: "6px 0" }}>{renderFormattedInline(block.text)}</p>;
  }
}
