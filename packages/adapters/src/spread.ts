import type { DepthLayer, SpreadResult } from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_SPREAD } from "@frame/types";

/** Static Layer 2 metadata (depth map). */
export async function getSpreadDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_SPREAD };
}

const PLATFORM_LEXICON: { canonical: string; patterns: RegExp[] }[] = [
  { canonical: "Fox News", patterns: [/\bfox\s*news\b/i, /\bfoxnews\b/i] },
  { canonical: "Breitbart", patterns: [/\bbreitbart\b/i] },
  { canonical: "Daily Caller", patterns: [/\bdaily\s+caller\b/i] },
  { canonical: "The New York Times", patterns: [/\bnew\s+york\s+times\b/i, /\bnyt\b/i] },
  { canonical: "CNN", patterns: [/\bcnn\b/i] },
  { canonical: "MSNBC", patterns: [/\bmsnbc\b/i] },
  { canonical: "The Washington Post", patterns: [/\bwashington\s+post\b/i, /\bwa\s*po\b/i] },
  { canonical: "The Wall Street Journal", patterns: [/\bwall\s+street\s+journal\b/i, /\bwsj\b/i] },
  { canonical: "HuffPost", patterns: [/\bhuff(?:ington)?\s*post\b/i] },
  { canonical: "Politico", patterns: [/\bpolitico\b/i] },
  { canonical: "The Hill", patterns: [/\bthe\s+hill\b/i] },
  { canonical: "NBC News", patterns: [/\bnbc\s+news\b/i] },
  { canonical: "ABC News", patterns: [/\babc\s+news\b/i] },
  { canonical: "CBS News", patterns: [/\bcbs\s+news\b/i] },
  { canonical: "NPR", patterns: [/\bnpr\b/i] },
  { canonical: "BBC", patterns: [/\bbbc\b/i] },
  { canonical: "The Guardian", patterns: [/\bthe\s+guardian\b/i] },
  { canonical: "Reuters", patterns: [/\breuters\b/i] },
  { canonical: "Associated Press", patterns: [/\bassociated\s+press\b/i, /\bap\s+news\b/i] },
  { canonical: "Drudge Report", patterns: [/\bdrudge\b/i] },
  { canonical: "Infowars", patterns: [/\binfowars\b/i] },
  { canonical: "Newsmax", patterns: [/\bnewsmax\b/i] },
  { canonical: "One America News", patterns: [/\bone\s+america\s+news\b/i, /\boan\b/i] },
  { canonical: "Substack", patterns: [/\bsubstack\b/i] },
  { canonical: "Reddit", patterns: [/\breddit\b/i] },
  {
    canonical: "Twitter / X",
    patterns: [/\btwitter\b/i, /\btwitter\s*\/\s*x\b/i, /\bx\.com\b/i],
  },
  { canonical: "Facebook", patterns: [/\bfacebook\b/i] },
  { canonical: "YouTube", patterns: [/\byoutube\b/i] },
  { canonical: "TikTok", patterns: [/\btiktok\b/i] },
  { canonical: "Telegram", patterns: [/\btelegram\b/i] },
  { canonical: "Truth Social", patterns: [/\btruth\s+social\b/i] },
  { canonical: "Gab", patterns: [/\bgab\b/i] },
  { canonical: "Parler", patterns: [/\bparler\b/i] },
  { canonical: "Gettr", patterns: [/\bgettr\b/i] },
];

function trimCanon(s: string): string {
  return s.trim();
}

/** Canonical platform / outlet labels mentioned in text (same lexicon as spread layer). */
export function extractPlatformsMentionedFromNarrative(text: string): string[] {
  const found = new Set<string>();
  for (const { canonical, patterns } of PLATFORM_LEXICON) {
    if (patterns.some((re) => re.test(text))) {
      found.add(trimCanon(canonical));
    }
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

const INDICATOR_RULES: { re: RegExp; label: string }[] = [
  { re: /\bwent\s+viral\b/i, label: "went viral" },
  { re: /\bpicked\s+up\s+by\b/i, label: "picked up by" },
  { re: /\bshared\s+across\b/i, label: "shared across" },
  { re: /\bappeared\s+on\s+multiple\b/i, label: "appeared on multiple" },
  { re: /\bsurfaced\s+on\b/i, label: "surfaced on (outlet cascade)" },
  { re: /\bcross[-\s]?posted\b/i, label: "cross-posted" },
  { re: /\bsyndicat/i, label: "syndication language" },
  { re: /\brepublished\b/i, label: "republished" },
  { re: /\bcirculat/i, label: "circulation / resharing" },
  { re: /\bamplif/i, label: "amplification" },
  { re: /\becho\s+chamber\b/i, label: "echo chamber" },
  { re: /\bcoordinated\b/i, label: "coordinated distribution (heuristic phrase)" },
  { re: /\bsimultaneously\b/i, label: "simultaneous appearance" },
  { re: /\bsame\s+(?:news\s+)?cycle\b/i, label: "same news cycle" },
  { re: /\bin\s+lockstep\b/i, label: "in lockstep" },
  { re: /\bwithin\s+\d+\s*(?:hours?|hrs?)\b/i, label: "within a short hours window" },
  { re: /\bwithin\s+\d+\s*(?:minutes?|mins?)\b/i, label: "within minutes" },
  { re: /\bwithin\s+\d+\s*days?\b/i, label: "within a multi-day window" },
  { re: /\bat\s+roughly\s+the\s+same\s+time\b/i, label: "roughly the same time" },
];

const TIME_COMPRESSION_RES: RegExp[] = [
  /\bsimultaneously\b/i,
  /\bwithin\s+\d+\s*(?:hours?|hrs?|minutes?|mins?|days?)\b/i,
  /\bsame\s+day\b/i,
  /\bsame\s+hour\b/i,
  /\bin\s+rapid\s+succession\b/i,
  /\bovernight\b/i,
];

function detectTimeCompression(text: string): boolean {
  return TIME_COMPRESSION_RES.some((re) => re.test(text));
}

function collectPlatforms(text: string): string[] {
  const found = new Set<string>();
  for (const { canonical, patterns } of PLATFORM_LEXICON) {
    const c = trimCanon(canonical);
    if (patterns.some((re) => re.test(text))) {
      found.add(c);
    }
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

function collectIndicators(text: string, platformCount: number): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const { re, label } of INDICATOR_RULES) {
    if (re.test(text) && !seen.has(label)) {
      seen.add(label);
      out.push(label);
    }
  }
  if (
    platformCount >= 2 &&
    /\bappeared\b/i.test(text) &&
    !seen.has("multi-outlet beat (heuristic)")
  ) {
    out.push("multi-outlet beat (heuristic)");
  }
  return out;
}

function tierFor(
  platforms: number,
  indicators: number,
  timeCompression: boolean,
): ConfidenceTier {
  if (platforms >= 3 && (timeCompression || indicators >= 2)) {
    return ConfidenceTier.CrossCorroborated;
  }
  if (platforms >= 2 || indicators >= 1 || timeCompression) {
    return ConfidenceTier.SingleSource;
  }
  return ConfidenceTier.StructuralHeuristic;
}

/**
 * Layer 2 spread heuristics from narrative text (no external APIs).
 */
export async function getSpreadLayer(input: { narrative: string }): Promise<SpreadResult> {
  const raw = input.narrative?.trim() ?? "";
  if (!raw) {
    throw new Error("narrative is required");
  }
  const text = raw;
  const platforms_mentioned = collectPlatforms(text);
  const time_compression = detectTimeCompression(text);
  let spread_indicators = collectIndicators(text, platforms_mentioned.length);

  const absent_fields: string[] = [];
  if (platforms_mentioned.length === 0) {
    absent_fields.push("platforms_mentioned");
  }
  if (spread_indicators.length === 0) {
    absent_fields.push("spread_indicators");
  }

  const confidence_tier = tierFor(
    platforms_mentioned.length,
    spread_indicators.length,
    time_compression,
  );

  return {
    platforms_mentioned,
    spread_indicators,
    time_compression,
    confidence_tier,
    absent_fields,
  };
}
