/* Deterministic pseudo-random helpers shared by anything that needs
 * reproducible "fake" data -- demo seed data (demoData.ts) and synthetic
 * history detail (lapSynthesis.ts) alike, so reloading or re-expanding a
 * card never shows different numbers than last time. */

/** mulberry32 — small, deterministic, good enough for seed/demo data. */
export function seededRandom(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Turns a stable string (e.g. an activity id) into a numeric seed, so
 *  content keyed by that string gets its own fixed-but-arbitrary stream of
 *  "random" numbers instead of everything sharing one global sequence. */
export function hashStringToSeed(text: string): number {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (Math.imul(hash, 31) + text.charCodeAt(i)) | 0;
  }
  return hash;
}
