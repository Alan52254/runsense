import React from "react";
import type { CSSProperties } from "react";
import { parseMarkdownBlocks } from "../lib/markdownBlocks.ts";
import type { BlockType } from "../lib/markdownBlocks.ts";

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

    case "list": {
      const items = block.items.map((item, idx) => <li key={idx}>{renderFormattedInline(item)}</li>);
      return block.ordered ? (
        <ol className="md-list md-list--ordered" style={{ "--md-start": block.start } as CSSProperties}>{items}</ol>
      ) : (
        <ul className="md-list">{items}</ul>
      );
    }

    case "quote":
      // a quiet indented aside under a thin neutral rule, not an accent tab
      return <blockquote className="md-quote">{renderFormattedInline(block.text)}</blockquote>;

    case "hr":
      return <hr className="md-rule" />;

    case "paragraph":
      return <p className="md-p">{renderFormattedInline(block.text)}</p>;
  }
}
