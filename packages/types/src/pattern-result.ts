/** Fixed tier for heuristic pattern matches (Layer 5). */
export const PATTERN_MATCH_TIER = "PATTERN_MATCH" as const;
export type PatternMatchTier = typeof PATTERN_MATCH_TIER;

export interface PatternMatchEntry {
  pattern_id: string;
  criteria_met: string[];
  confidence_tier: PatternMatchTier;
}

export interface PatternResult {
  patterns_checked: number;
  matches: PatternMatchEntry[];
  /** Non-null when `matches` is empty; null when at least one match exists. */
  no_match_reason: string | null;
}
