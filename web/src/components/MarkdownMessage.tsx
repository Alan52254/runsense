import React from "react";

interface MarkdownMessageProps {
  content: string;
  isStreaming?: boolean;
}

export function MarkdownMessage({ content, isStreaming }: MarkdownMessageProps) {
  // Parse message into blocks: paragraphs, lists, tables, headers, blockquotes
  const blocks = parseMarkdownBlocks(content);

  return (
    <div className="markdown-render">
      {blocks.map((block, index) => (
        <React.Fragment key={index}>{renderBlock(block)}</React.Fragment>
      ))}
      {isStreaming && <span className="md-caret" aria-hidden="true" />}
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
              <strong key={index} className="md-strong">
                {part.slice(2, -2)}
              </strong>
            );
          }
          if (part.startsWith("`") && part.endsWith("`")) {
            return (
              <code key={index} className="md-code">
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
        <div className={`md-heading md-heading--${block.level}`}>
          {renderFormattedInline(block.text)}
        </div>
      );

    case "table":
      return (
        <div className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {block.headers.map((h, idx) => (
                  <th key={idx}>{renderFormattedInline(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td key={cIdx}>{renderFormattedInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "list":
      return (
        <ul className="md-list">
          {block.items.map((item, idx) => (
            <li key={idx}>{renderFormattedInline(item)}</li>
          ))}
        </ul>
      );

    case "quote":
      // a quiet indented aside under a thin neutral rule, not an accent tab
      return <blockquote className="md-quote">{renderFormattedInline(block.text)}</blockquote>;

    case "hr":
      return <hr className="md-rule" />;

    case "paragraph":
      return <p className="md-p">{renderFormattedInline(block.text)}</p>;
  }
}
