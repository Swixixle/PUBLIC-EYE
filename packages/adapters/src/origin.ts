import type { DepthLayer, OriginResult } from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_ORIGIN } from "@frame/types";

/** Static Layer 3 metadata (depth map). */
export async function getOriginDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_ORIGIN };
}

const FIRST_INSTANCE_RULES: { re: RegExp; label: string }[] = [
  { re: /\bfirst\s+reported\b/i, label: "first reported" },
  { re: /\boriginally\s+posted\b/i, label: "originally posted" },
  { re: /\btraced\s+back\s+to\b/i, label: "traced back to" },
  { re: /\bfirst\s+appeared\b/i, label: "first appeared" },
  { re: /\bfirst\s+posted\b/i, label: "first posted" },
  { re: /\bfirst\s+published\b/i, label: "first published" },
  { re: /\bearliest\s+documented\b/i, label: "earliest documented" },
  { re: /\binternet-born\b/i, label: "internet-born (origin framing)" },
  { re: /\bearliest\s+known\b/i, label: "earliest known" },
  { re: /\boriginated\b/i, label: "originated" },
  { re: /\bfirst\s+instance\b/i, label: "first instance" },
  { re: /\bwhere\s+it\s+(?:all\s+)?began\b/i, label: "where it began" },
  { re: /\bsource\s+of\s+the\s+story\b/i, label: "source of the story" },
  { re: /\binitially\s+(?:posted|published|shared)\b/i, label: "initially posted/published/shared" },
];

const DATE_PATTERNS: RegExp[] = [
  /\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b/i,
  /\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b/i,
  /\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b/i,
  /\bin\s+\d{4}\b/i,
  /\b\d{4}-\d{2}-\d{2}\b/,
  /\b(?:Spring|Summer|Fall|Autumn)\s+\d{4}\b/i,
];

function hasDatableTime(text: string): boolean {
  return DATE_PATTERNS.some((re) => re.test(text));
}

function temporalSnippet(text: string): string | null {
  for (const re of DATE_PATTERNS) {
    const m = text.match(re);
    if (m) return m[0].trim();
  }
  return null;
}

function collectFirstInstanceIndicators(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const { re, label } of FIRST_INSTANCE_RULES) {
    if (re.test(text) && !seen.has(label)) {
      seen.add(label);
      out.push(label);
    }
  }
  return out;
}

/** Exported for Layer 4 actor candidate extraction (same heuristics). */
export function extractOriginSeedingEntities(text: string): string[] {
  const actors = new Set<string>();

  /** Person/org token run; ends before ` on ` / ` in ` / punctuation so glue phrases are not captured. */
  const nameCap = (prefix: string) =>
    new RegExp(
      prefix +
        String.raw`([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})(?=,|\.|$|\s+(?:on|in|at|with|for|to)\b)`,
      "gi",
    );

  const byPatterns = [
    nameCap(String.raw`\b(?:first\s+)?posted\s+by\s+`),
    nameCap(String.raw`\b(?:first\s+)?published\s+by\s+`),
    nameCap(String.raw`\bcreated\s+by\s+`),
    nameCap(String.raw`\bcredited\s+to\s+`),
    nameCap(String.raw`\battributed\s+to\s+`),
    nameCap(String.raw`\btraced\s+back\s+to\s+`),
  ];
  for (const re of byPatterns) {
    let m: RegExpExecArray | null;
    const r = new RegExp(re.source, re.flags);
    while ((m = r.exec(text)) !== null) {
      const name = (m[1] || "").replace(/\s+/g, " ").trim();
      if (name.length >= 2) actors.add(name);
    }
  }

  const forum = text.match(
    /\bon\s+the\s+([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)\s+forums?\b/i,
  );
  if (forum?.[1]) {
    actors.add(`${forum[1].trim()} forums`);
  }

  const onSite = text.match(
    /\bon\s+([A-Z][A-Za-z0-9]+(?:\.[A-Za-z0-9]+)+)\b/,
  );
  if (onSite?.[1] && /\./.test(onSite[1])) {
    actors.add(onSite[1].trim());
  }

  return [...actors].sort((a, b) => a.localeCompare(b));
}

function hasVenueHook(text: string): boolean {
  return (
    /\bon\s+the\s+[A-Z][A-Za-z]+\s+forums?\b/i.test(text) ||
    /\bon\s+[A-Z][A-Za-z]+(?:\.[a-z]{2,})+/i.test(text) ||
    /\bat\s+[A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*\b/.test(text)
  );
}

function computeAnchorExists(
  text: string,
  indicators: string[],
  actors: string[],
  hasDate: boolean,
): boolean {
  if (indicators.length === 0 || !hasDate) return false;
  return actors.length > 0 || hasVenueHook(text);
}

function buildAnchorDescription(
  text: string,
  actors: string[],
  hasDate: boolean,
  anchorExists: boolean,
): string | null {
  if (!anchorExists) return null;
  const ts = temporalSnippet(text);
  const hook = actors.length ? actors.join(", ") : "unspecified named hook";
  const when = ts ?? (hasDate ? "date-like token present" : "no clear date token");
  return (
    `Heuristic anchor: narrative cites ${hook} with timing ${when} ` +
    `as a first-instance locus (not verified against primary records in this pass).`
  );
}

function originTier(
  anchorExists: boolean,
  indicators: number,
  actors: number,
  hasDate: boolean,
): ConfidenceTier {
  if (anchorExists && indicators >= 2 && actors >= 1 && hasDate) {
    return ConfidenceTier.CrossCorroborated;
  }
  if (anchorExists && (indicators >= 1 || actors >= 1)) {
    return ConfidenceTier.SingleSource;
  }
  if (indicators >= 1 || actors >= 1) {
    return ConfidenceTier.StructuralHeuristic;
  }
  return ConfidenceTier.StructuralHeuristic;
}

function collectAbsentFields(
  indicators: string[],
  actors: string[],
  hasDate: boolean,
  anchorExists: boolean,
): string[] {
  const absent: string[] = [];
  if (indicators.length === 0) absent.push("first_instance_indicators");
  if (actors.length === 0) absent.push("seeding_actors");
  if (!hasDate) absent.push("temporal_anchor");
  if (!anchorExists) absent.push("datable_sourceable_first_instance");
  return absent;
}

/**
 * Layer 3 origin heuristics from narrative text (no external APIs).
 */
export async function getOriginLayer(input: { narrative: string }): Promise<OriginResult> {
  const raw = input.narrative?.trim() ?? "";
  if (!raw) {
    throw new Error("narrative is required");
  }
  const text = raw;
  const first_instance_indicators = collectFirstInstanceIndicators(text);
  const seeding_actors = extractOriginSeedingEntities(text);
  const hasDate = hasDatableTime(text);
  const anchor_exists = computeAnchorExists(
    text,
    first_instance_indicators,
    seeding_actors,
    hasDate,
  );
  const anchor_description = buildAnchorDescription(
    text,
    seeding_actors,
    hasDate,
    anchor_exists,
  );
  const confidence_tier = originTier(
    anchor_exists,
    first_instance_indicators.length,
    seeding_actors.length,
    hasDate,
  );
  const absent_fields = collectAbsentFields(
    first_instance_indicators,
    seeding_actors,
    hasDate,
    anchor_exists,
  );

  return {
    first_instance_indicators,
    seeding_actors,
    anchor_exists,
    anchor_description,
    confidence_tier,
    absent_fields,
  };
}
