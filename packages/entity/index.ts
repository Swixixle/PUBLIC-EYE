import type {
  DisambiguationResult,
  EntityCandidate,
} from "@frame/types";

export const DEFAULT_CONFIDENCE_FLOOR = 0.72;

/**
 * Picks the best entity candidate for a query string using lexical overlap
 * between the query and candidate labels. Results below `confidenceFloor`
 * do not set `chosen` (but alternatives are still returned).
 */
export function disambiguateEntity(
  query: string,
  candidates: EntityCandidate[],
  confidenceFloor: number = DEFAULT_CONFIDENCE_FLOOR,
): DisambiguationResult {
  const normalizedQuery = normalize(query);
  const scored = candidates.map((c) => ({
    candidate: c,
    effectiveScore: Math.max(c.score, overlapScore(normalizedQuery, normalize(c.label))),
  }));

  scored.sort((a, b) => b.effectiveScore - a.effectiveScore);
  const alternatives = scored.map((s) => ({
    ...s.candidate,
    score: round4(s.effectiveScore),
  }));

  const top = alternatives[0];
  const meetsFloor = top !== undefined && top.score >= confidenceFloor;

  return {
    query,
    chosen: meetsFloor ? top : undefined,
    alternatives,
    meetsFloor,
  };
}

function normalize(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

function tokenSet(s: string): Set<string> {
  return new Set(s.split(" ").filter((t) => t.length > 1));
}

/** Jaccard-like overlap boosted into 0..1 for UX. */
function overlapScore(a: string, b: string): number {
  const A = tokenSet(a);
  const B = tokenSet(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter += 1;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000;
}
