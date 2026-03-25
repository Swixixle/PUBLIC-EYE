import type { DepthLayer, PatternResult } from "@frame/types";
import { DEPTH_LAYER_PATTERN, PATTERN_MATCH_TIER } from "@frame/types";
import { getPatternLibrary, type PatternRecord } from "@frame/pattern-lib";

/** Static Layer 5 metadata (depth map). */
export async function getPatternDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_PATTERN };
}

function structuralCriteria(record: PatternRecord, narrative: string): string[] {
  const out: string[] = [];
  const t = narrative;

  if (record.id === "coordinated-lateral-spread-v1") {
    if (/\b72\b|\b72\s*h(?:ours?)?/i.test(t)) {
      out.push("structural:72h_window_reference");
    }
    if (/\b(?:org|organi[sz]ation|organizations|orgs)\b/i.test(t) || /multiple\s+org/i.test(t)) {
      out.push("structural:multi_org_language");
    }
    if (/\b(?:three|3|3\+)\s+org/i.test(t)) {
      out.push("structural:three_or_more_orgs_language");
    }
  }

  if (record.id === "astroturf-grassroots-v1") {
    if (/\b96\b|\b96\s*h(?:ours?)?/i.test(t)) {
      out.push("structural:96h_window_reference");
    }
    if (/\b(?:5|five|five\+|≥\s*5)\s*(?:accounts|account)\b/i.test(t)) {
      out.push("structural:min_accounts_language");
    }
    if (/\b(?:unaffiliated|appearing\s+unaffiliated)\b/i.test(t)) {
      out.push("structural:unaffiliated_appearance_language");
    }
  }

  return out;
}

function scoreAgainstPattern(narrative: string, record: PatternRecord): { met: boolean; criteria_met: string[] } {
  const lower = narrative.toLowerCase();
  const criteria_met: string[] = [];
  const { keywords, min_hits } = record.detection;

  for (const kw of keywords) {
    if (lower.includes(kw.toLowerCase())) {
      criteria_met.push(`keyword:${kw}`);
    }
  }

  criteria_met.push(...structuralCriteria(record, narrative));

  const unique = [...new Set(criteria_met)];
  const met = unique.length >= min_hits;
  return { met, criteria_met: unique };
}

/**
 * Layer 5 heuristic: match narrative text against the catalog (keywords + structural).
 */
export async function getPatternLayer(input: { narrative: string }): Promise<PatternResult> {
  const narrative = input.narrative?.trim();
  if (!narrative) {
    throw new Error("narrative is required");
  }

  const library = getPatternLibrary();
  const patterns_checked = library.length;
  const matches: PatternResult["matches"] = [];

  for (const record of library) {
    const { met, criteria_met } = scoreAgainstPattern(narrative, record);
    if (met) {
      matches.push({
        pattern_id: record.id,
        criteria_met,
        confidence_tier: PATTERN_MATCH_TIER,
      });
    }
  }

  const no_match_reason: string | null =
    matches.length === 0
      ? "No pattern met its keyword/structural minimum thresholds for this narrative."
      : null;

  return {
    patterns_checked,
    matches,
    no_match_reason,
  };
}
