/** Property names set by every `style={{ … }}` object literal in a TSX source. */
export function inlineStyleKeys(source: string): { line: number; keys: string[] }[] {
  const found: { line: number; keys: string[] }[] = [];
  const marker = /style=\{\{/g;
  for (let match = marker.exec(source); match; match = marker.exec(source)) {
    let depth = 2;
    let index = match.index + match[0].length;
    const start = index;
    let quote = "";
    for (; index < source.length && depth > 0; index++) {
      const ch = source[index];
      if (quote) { if (ch === "\\") index++; else if (ch === quote) quote = ""; continue; }
      if (ch === '"' || ch === "'" || ch === "`") quote = ch;
      else if (ch === "{") depth++;
      else if (ch === "}") depth--;
    }
    const body = source.slice(start, index - 2);
    found.push({ line: source.slice(0, match.index).split("\n").length, keys: topLevelKeys(body) });
  }
  return found;
}

function topLevelKeys(body: string): string[] {
  const keys: string[] = [];
  let depth = 0;
  let quote = "";
  let piece = "";
  const flush = () => {
    const text = piece.trim();
    piece = "";
    if (!text) return;
    if (text.startsWith("...")) return void keys.push("...");
    const key = /^(?:"([^"]+)"|'([^']+)'|([\w$]+))\s*(?::|$|,)/.exec(text);
    keys.push(key ? (key[1] ?? key[2] ?? key[3]) : text);
  };
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (quote) { piece += ch; if (ch === "\\") piece += body[++i] ?? ""; else if (ch === quote) quote = ""; continue; }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if ("{[(".includes(ch)) depth++;
    else if ("}])".includes(ch)) depth--;
    if (ch === "," && depth === 0) flush(); else piece += ch;
  }
  flush();
  return keys;
}
