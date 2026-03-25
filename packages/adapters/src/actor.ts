import type { DepthLayer, ActorLayerResult, ActorRecord } from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_ACTOR } from "@frame/types";
import { findActorByExactNameOrAlias, getActor } from "@frame/actor-ledger";
import { extractOriginSeedingEntities } from "./origin.js";
import { extractPlatformsMentionedFromNarrative } from "./spread.js";

/** Static Layer 4 metadata (depth map). */
export async function getActorDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_ACTOR };
}

function actorNameToSlug(name: string): string {
  if (!name || typeof name !== "string") return "unknown";
  const s = name
    .toLowerCase()
    .trim()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
  return s || "unknown";
}

function actorSlugCandidates(name: string): string[] {
  const trimmed = name.trim();
  const primary = actorNameToSlug(trimmed);
  const parenStripped = trimmed.replace(/\([^)]*\)/g, "").trim();
  const secondary =
    parenStripped && parenStripped !== trimmed ? actorNameToSlug(parenStripped) : null;
  const ordered =
    secondary && secondary !== primary ? [primary, secondary] : [primary];
  return [...new Set(ordered)];
}

/** Strip venue suffixes so "Something Awful forums" also tries "Something Awful". */
function candidateVariants(raw: string): string[] {
  const t = raw.trim();
  if (!t) return [];
  const out = new Set<string>([t]);
  const noForums = t.replace(/\s+forums?$/i, "").trim();
  if (noForums && noForums !== t) out.add(noForums);
  return [...out];
}

function tryResolveActorCandidate(raw: string): ActorRecord | null {
  for (const variant of candidateVariants(raw)) {
    for (const slug of actorSlugCandidates(variant)) {
      if (slug === "unknown") continue;
      const row = getActor(slug);
      if (row) return row;
    }
    const byName = findActorByExactNameOrAlias(variant);
    if (byName) return byName;
  }
  return null;
}

function mergeCandidates(text: string): string[] {
  const set = new Set<string>();
  for (const x of extractOriginSeedingEntities(text)) {
    if (x.trim()) set.add(x.trim());
  }
  for (const x of extractPlatformsMentionedFromNarrative(text)) {
    if (x.trim()) set.add(x.trim());
  }
  return [...set].sort((a, b) => a.localeCompare(b));
}

function tierFor(found: ActorRecord[], absentCount: number): ConfidenceTier {
  if (found.length === 0) {
    return ConfidenceTier.StructuralHeuristic;
  }
  const ledgerCross = found.some((r) =>
    r.events.some((e) => e.confidence_tier === ConfidenceTier.CrossCorroborated),
  );
  if (ledgerCross && absentCount === 0) {
    return ConfidenceTier.CrossCorroborated;
  }
  return ConfidenceTier.SingleSource;
}

function absentFieldsFor(
  candidates: number,
  found: number,
  absent: number,
): string[] {
  const out: string[] = [];
  if (candidates === 0) out.push("extracted_candidates");
  if (found === 0 && candidates > 0) out.push("ledger_matches");
  if (absent > 0) out.push("actors_not_in_ledger");
  return out;
}

/**
 * Layer 4: narrative entity mentions resolved against the append-only actor ledger (local JSON).
 */
export async function getActorLayer(input: { narrative: string }): Promise<ActorLayerResult> {
  const raw = input.narrative?.trim() ?? "";
  if (!raw) {
    throw new Error("narrative is required");
  }
  const candidates = mergeCandidates(raw);
  const foundBySlug = new Map<string, ActorRecord>();
  const actors_absent: ActorLayerResult["actors_absent"] = [];

  for (const name of candidates) {
    const rec = tryResolveActorCandidate(name);
    if (rec) {
      if (!foundBySlug.has(rec.slug)) {
        foundBySlug.set(rec.slug, rec);
      }
    } else {
      actors_absent.push({ name, absent: true });
    }
  }

  const actors_found = [...foundBySlug.values()].sort((a, b) =>
    a.slug.localeCompare(b.slug),
  );

  const confidence_tier = tierFor(actors_found, actors_absent.length);
  const absent_fields = absentFieldsFor(
    candidates.length,
    actors_found.length,
    actors_absent.length,
  );

  return {
    actors_found,
    actors_absent,
    confidence_tier,
    absent_fields,
  };
}
