import Anthropic from "@anthropic-ai/sdk";
import type {
  ActorEvent,
  ActorLookupSource,
  DepthLayer,
  ActorLayerResult,
  ActorRecord,
} from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_ACTOR } from "@frame/types";
import { lookupInternetArchive } from "./sources/internet-archive.js";
import { lookupChroniclingAmerica } from "./sources/chronicling-america.js";
import {
  findActorByExactNameOrAlias,
  getActor,
  listLedgerSearchHints,
} from "@frame/actor-ledger";
import { extractOriginSeedingEntities } from "./origin.js";
import { getSurfaceLayer } from "./surface.js";
import { extractPlatformsMentionedFromNarrative } from "./spread.js";

/** Static Layer 4 metadata (depth map). */
export async function getActorDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_ACTOR };
}

const WD_API = "https://www.wikidata.org/w/api.php";
const UA = "FrameActorLayer/1.0 (https://github.com/Swixixle/FRAME)";

const SURFACE_MODEL_DEFAULT_CHAIN = ["claude-haiku-4-5", "claude-3-haiku-20240307"] as const;

/** Shared promises so Internet Archive + Chronicling America run in parallel with Wikidata / Wikipedia / web. */
export type DynamicLookupArchivePromises = {
  ia: Promise<ActorEvent[]>;
  ca: Promise<ActorEvent[]>;
};

function mergeArchiveStack(rec: ActorRecord, iaEvents: ActorEvent[], caEvents: ActorEvent[]): ActorRecord {
  const base: ActorLookupSource[] = rec.lookup_source ? [...rec.lookup_source] : [];
  if (iaEvents.length && !base.includes("internet_archive")) base.push("internet_archive");
  if (caEvents.length && !base.includes("chronicling_america")) base.push("chronicling_america");
  if (iaEvents.length === 0 && caEvents.length === 0) {
    return { ...rec, lookup_source: base };
  }
  return {
    ...rec,
    lookup_source: base,
    events: [...rec.events, ...iaEvents, ...caEvents],
  };
}

function surfaceModelCandidates(): string[] {
  const env = process.env.ANTHROPIC_SURFACE_MODEL?.trim();
  if (env) return [env];
  return [...SURFACE_MODEL_DEFAULT_CHAIN];
}

function isLikelyInvalidModelError(e: unknown): boolean {
  if (!e || typeof e !== "object") return false;
  const err = e as { status?: number; message?: string };
  const msg = typeof err.message === "string" ? err.message : String(e);
  if (err.status === 404) return true;
  return /\bmodel\b/i.test(msg) && /not\s*found|invalid|does\s*not\s*exist|unknown/i.test(msg);
}

function extractJsonObject(text: string): string {
  let t = text.trim();
  if (t.startsWith("```")) {
    t = t.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "");
  }
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) {
    return t.slice(start, end + 1);
  }
  return t;
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

function shortHash(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h).toString(36).slice(0, 8);
}

function formatWikidataTime(raw: { time?: string; precision?: number } | undefined): string {
  if (!raw?.time) return "";
  const t = raw.time.replace(/^\+/, "");
  const match = t.match(/^(-?\d+)-(\d{2})-(\d{2})/);
  if (!match) return "";
  const [, yStr, mo, da] = match;
  const prec = raw.precision ?? 11;
  if (prec <= 9) return `${yStr}-01-01`;
  if (prec <= 10) return `${yStr}-${mo}-01`;
  return `${yStr}-${mo}-${da}`;
}

/** Opening paragraph from English Wikipedia REST summary (underscores in path). */
async function fetchWikipediaPageExtract(titleUnderscores: string): Promise<string | null> {
  const t = titleUnderscores.trim();
  if (t.length < 2) return null;
  const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(t)}`;
  try {
    const r = await fetch(url, { headers: { "User-Agent": UA } });
    if (r.status === 404 || !r.ok) return null;
    const data = (await r.json()) as {
      type?: string;
      extract?: string;
    };
    if (data.type === "disambiguation") return null;
    const extract = (data.extract ?? "").trim();
    return extract.length > 0 ? extract : null;
  } catch {
    return null;
  }
}

/** Wikidata entity search + optional P571 for event date. */
export async function lookupWikidata(name: string): Promise<ActorRecord | null> {
  const q = name.trim();
  if (q.length < 2) return null;
  try {
    const searchUrl = `${WD_API}?action=wbsearchentities&search=${encodeURIComponent(q)}&language=en&format=json&limit=8`;
    const sr = await fetch(searchUrl, { headers: { "User-Agent": UA } });
    if (!sr.ok) return null;
    const sd = (await sr.json()) as {
      search?: Array<{ id: string; label?: string; description?: string }>;
    };
    const hits = sd.search ?? [];
    if (hits.length === 0) return null;
    const qLow = q.toLowerCase();
    const exactLabel = hits.filter((h) => (h.label ?? "").trim().toLowerCase() === qLow);
    const pool = exactLabel.length > 0 ? exactLabel : hits;
    const folkloreHint = /folklore|mytholog|legend|deity|spirit|creature|fairy|slavic|russian tales/i;
    const likelyWrong = /recording|album|song|instrumental|composer|soundtrack|film score|single \(/i;
    const rank = (h: { description?: string }) => {
      const d = h.description ?? "";
      let s = 0;
      if (folkloreHint.test(d)) s += 3;
      if (likelyWrong.test(d)) s -= 2;
      return s;
    };
    const sorted = [...pool].sort((a, b) => rank(b) - rank(a));
    const first = sorted[0];
    if (!first?.id) return null;
    const id = first.id;
    const label = first.label ?? q;
    let description = first.description ?? "";
    let dateStr = "";

    const entUrl = `${WD_API}?action=wbgetentities&ids=${id}&languages=en&props=claims|descriptions|labels|sitelinks&format=json`;
    const er = await fetch(entUrl, { headers: { "User-Agent": UA } });
    let wikipedia_title: string | undefined;
    if (er.ok) {
      const ed = (await er.json()) as {
        entities?: Record<
          string,
          {
            descriptions?: { en?: { value?: string } };
            sitelinks?: { enwiki?: { title?: string } };
            claims?: Record<
              string,
              Array<{ mainsnak?: { datavalue?: { value?: unknown } } }>
            >;
          }
        >;
      };
      const entity = ed.entities?.[id];
      if (entity?.descriptions?.en?.value) {
        description = entity.descriptions.en.value;
      }
      const enwiki = entity?.sitelinks?.enwiki?.title?.trim();
      if (enwiki) {
        wikipedia_title = enwiki.replace(/ /g, "_");
      }
      const p571 = entity?.claims?.P571?.[0]?.mainsnak?.datavalue?.value as
        | { time?: string; precision?: number }
        | undefined;
      dateStr = formatWikidataTime(p571);
    }

    const descFinal = description || `Wikidata entity ${id} (${label})`;
    return {
      slug: `wd-${id.toLowerCase()}`,
      name: label,
      aliases: q !== label ? [q] : [],
      lookup_source: ["wikidata"],
      wikidata_id: id,
      wikipedia_title,
      events: [
        {
          date: dateStr || "unknown",
          type: "wikidata_entity",
          description: descFinal,
          source: "Wikidata — dynamically retrieved, not hand-verified",
          confidence_tier: ConfidenceTier.SingleSource,
        },
      ],
    };
  } catch {
    return null;
  }
}

/** English Wikipedia REST summary (first matching title). */
export async function lookupWikipedia(name: string): Promise<ActorRecord | null> {
  const q = name.trim();
  if (q.length < 2) return null;
  const titleUnderscore = q.replace(/\s+/g, "_");
  const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(titleUnderscore)}`;
  try {
    const r = await fetch(url, { headers: { "User-Agent": UA } });
    if (r.status === 404) return null;
    if (!r.ok) return null;
    const data = (await r.json()) as {
      type?: string;
      title?: string;
      extract?: string;
    };
    if (data.type === "disambiguation") return null;
    const extract = (data.extract ?? "").trim();
    if (!extract) return null;
    const pageTitle = data.title ?? q.replace(/_/g, " ");
    const titleForUrl = pageTitle.replace(/ /g, "_");
    const yearMatch = extract.match(/\b(1[0-9]{3}|20[0-9]{2})\b/);
    const dateStr = yearMatch ? `${yearMatch[1]}-01-01` : "unknown";
    const slug = `wiki-${actorNameToSlug(pageTitle)}`;
    return {
      slug,
      name: pageTitle,
      aliases: [],
      lookup_source: ["wikipedia"],
      wikipedia_title: titleForUrl,
      events: [
        {
          date: dateStr,
          type: "wikipedia_summary",
          description: extract.slice(0, 1200),
          source: "Wikipedia REST summary — dynamically retrieved, not hand-verified",
          confidence_tier: ConfidenceTier.SingleSource,
        },
      ],
    };
  } catch {
    return null;
  }
}

async function anthropicJsonCompletion(prompt: string): Promise<string | null> {
  const key = process.env.ANTHROPIC_API_KEY?.trim();
  if (!key) return null;
  const client = new Anthropic({ apiKey: key });
  const candidates = surfaceModelCandidates();
  for (let i = 0; i < candidates.length; i++) {
    const model = candidates[i]!;
    try {
      const msg = await client.messages.create({
        model,
        max_tokens: 512,
        messages: [{ role: "user", content: prompt }],
      });
      const block = msg.content.find((b) => b.type === "text");
      if (block && block.type === "text") return block.text;
    } catch (e) {
      if (i < candidates.length - 1 && isLikelyInvalidModelError(e)) continue;
    }
  }
  return null;
}

/** Anthropic extraction — tier `structural_heuristic` on the synthetic event. */
export async function lookupWeb(name: string): Promise<ActorRecord | null> {
  const q = name.trim();
  if (q.length < 2) return null;

  const prompt =
    `Return only documented facts about ${JSON.stringify(q)} with sources. No speculation.\n\n` +
    `Return ONE JSON object only (no markdown) with keys exactly:\n` +
    `- "name": string (canonical label if known, else the query)\n` +
    `- "earliest_documented_date": string (YYYY or YYYY-MM-DD if you can cite; else "")\n` +
    `- "description": string (one factual sentence only; empty if none documented)\n` +
    `- "source_citation": string (short citation: work — date, publisher, or URL; empty if none)\n\n` +
    `Rules: documented facts only; if nothing is documented leave description and source_citation empty.`;

  const text = await anthropicJsonCompletion(prompt);
  if (!text) return null;
  let parsed: {
    name?: string;
    earliest_documented_date?: string;
    description?: string;
    source_citation?: string;
  };
  try {
    parsed = JSON.parse(extractJsonObject(text)) as typeof parsed;
  } catch {
    return null;
  }
  const desc = typeof parsed.description === "string" ? parsed.description.trim() : "";
  if (!desc) return null;
  const dateRaw =
    typeof parsed.earliest_documented_date === "string"
      ? parsed.earliest_documented_date.trim()
      : "";
  const dateStr = dateRaw || "unknown";
  const displayName =
    typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : q;
  const cite = typeof parsed.source_citation === "string" ? parsed.source_citation.trim() : "";

  return {
    slug: `web-${actorNameToSlug(displayName)}-${shortHash(q)}`,
    name: displayName,
    aliases: displayName !== q ? [q] : [],
    lookup_source: ["web_inference"],
    events: [
      {
        date: dateStr,
        type: "web_inference",
        description: desc,
        source:
          cite ||
          "Anthropic web inference — dynamically retrieved, not hand-verified (structural heuristic)",
        confidence_tier: ConfidenceTier.StructuralHeuristic,
      },
    ],
  };
}

/**
 * Run Layer 1 surface extraction on the Wikidata/Wikipedia anchor text so the actor row
 * carries forensic `what` / `cultural_substrate` / `who` / `when`, not only a one-line API blurb.
 */
async function enrichDynamicRecordWithSurface(rec: ActorRecord): Promise<ActorRecord> {
  const sources = rec.lookup_source ?? [];
  if (!sources.includes("wikidata") && !sources.includes("wikipedia")) {
    return rec;
  }
  const wikidataOneLiner = (rec.events[0]?.description ?? "").trim();
  let anchorNarrative = `${rec.name} — ${wikidataOneLiner}`.trim();
  if (anchorNarrative.length > 0 && !anchorNarrative.endsWith(".")) {
    anchorNarrative += ".";
  }

  let usedWikipediaExtract = false;
  if (sources.includes("wikidata")) {
    const titleForRest =
      rec.wikipedia_title?.trim() || rec.name.replace(/\s+/g, "_");
    const wpExtract = await fetchWikipediaPageExtract(titleForRest);
    if (wpExtract) {
      anchorNarrative = `${anchorNarrative} ${wpExtract}`.trim();
      usedWikipediaExtract = true;
    }
  }

  anchorNarrative = anchorNarrative.slice(0, 4000);
  if (anchorNarrative.length < 6) return rec;
  try {
    const surface = await getSurfaceLayer({ narrative: anchorNarrative });
    const anchorSource =
      sources.includes("wikidata") && rec.wikidata_id
        ? usedWikipediaExtract
          ? `Wikidata (${rec.wikidata_id}) + English Wikipedia extract; Layer 1 surface extraction`
          : `Wikidata anchor (${rec.wikidata_id}); Layer 1 surface extraction`
        : sources.includes("wikipedia") && rec.wikipedia_title
          ? `Wikipedia anchor (${rec.wikipedia_title}); Layer 1 surface extraction`
          : "External anchor; Layer 1 surface extraction";
    return {
      ...rec,
      what: surface.what,
      cultural_substrate: surface.cultural_substrate,
      what_confidence_tier: surface.what_confidence_tier,
      surface_who: surface.who,
      surface_when: surface.when,
      events: [
        {
          date: rec.events[0]?.date ?? "unknown",
          type: "layer1_trace",
          description: surface.what,
          source: anchorSource,
          confidence_tier: surface.what_confidence_tier,
        },
      ],
    };
  } catch {
    return rec;
  }
}

/**
 * Wikidata → Wikipedia → web inference, merged with Internet Archive + Chronicling America
 * (archive fetches run in parallel when `archive` passes shared promises from `getActorLayer`).
 */
export async function dynamicLookupChain(
  name: string,
  archive?: DynamicLookupArchivePromises,
): Promise<ActorRecord | null> {
  const iaP = archive?.ia ?? lookupInternetArchive(name);
  const caP = archive?.ca ?? lookupChroniclingAmerica(name);

  const wd = await lookupWikidata(name);
  let main: ActorRecord | null = null;
  if (wd) main = await enrichDynamicRecordWithSurface(wd);
  else {
    const wp = await lookupWikipedia(name);
    if (wp) main = await enrichDynamicRecordWithSurface(wp);
    else main = await lookupWeb(name);
  }

  const [iaEvents, caEvents] = await Promise.all([iaP, caP]);
  if (!main) {
    if (iaEvents.length === 0 && caEvents.length === 0) return null;
    const lookup_source: ActorLookupSource[] = [];
    if (iaEvents.length) lookup_source.push("internet_archive");
    if (caEvents.length) lookup_source.push("chronicling_america");
    return {
      slug: `hist-${actorNameToSlug(name)}-${shortHash(name)}`,
      name,
      aliases: [],
      lookup_source,
      events: [...iaEvents, ...caEvents],
    };
  }
  return mergeArchiveStack(main, iaEvents, caEvents);
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
      if (row) return { ...row, lookup_source: ["ledger"] };
    }
    const byName = findActorByExactNameOrAlias(variant);
    if (byName) return { ...byName, lookup_source: ["ledger"] };
  }
  return null;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Match ledger `name` / `alias` strings as whole phrases (longer hints first). */
function hintsMentionedInText(text: string): string[] {
  const hit: string[] = [];
  for (const hint of listLedgerSearchHints()) {
    const h = hint.trim();
    if (h.length < 2) continue;
    const re = new RegExp(`\\b${escapeRegExp(h)}\\b`, "i");
    if (re.test(text)) hit.push(h);
  }
  return hit;
}

/** "Baba Yaga was …", "Osiris is …" — helps entities not yet in the ledger. */
function subjectsFromIsWas(text: string): string[] {
  const out: string[] = [];
  const re = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|was)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const s = m[1].trim();
    if (s.length >= 2) out.push(s);
  }
  const reSight =
    /\b((?:[A-Z][a-z]+\s+){2,}[A-Z][a-z]+)\s+(?:sightings|reports|legend)\b/gi;
  while ((m = reSight.exec(text)) !== null) {
    const s = m[1].trim();
    if (s.length >= 2) out.push(s);
  }
  return out;
}

/** Narrative that is only a multi-word proper name, e.g. `Baba Yaga` (no verb clause). */
function bareProperNamePhrases(text: string): string[] {
  const t = text.trim();
  if (!t) return [];
  if (/^(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){1,4}$/.test(t)) {
    return [t];
  }
  return [];
}

function mergeCandidates(text: string): string[] {
  const set = new Set<string>();
  for (const x of extractOriginSeedingEntities(text)) {
    if (x.trim()) set.add(x.trim());
  }
  for (const x of extractPlatformsMentionedFromNarrative(text)) {
    if (x.trim()) set.add(x.trim());
  }
  for (const x of hintsMentionedInText(text)) {
    if (x.trim()) set.add(x.trim());
  }
  for (const x of subjectsFromIsWas(text)) {
    if (x.trim()) set.add(x.trim());
  }
  for (const x of bareProperNamePhrases(text)) {
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
 * Layer 4: narrative entity mentions resolved against the actor ledger; optional Wikidata → Wikipedia → web chain.
 */
export async function getActorLayer(input: { narrative: string }): Promise<ActorLayerResult> {
  const raw = input.narrative?.trim() ?? "";
  if (!raw) {
    throw new Error("narrative is required");
  }
  const candidates = mergeCandidates(raw);
  const foundBySlug = new Map<string, ActorRecord>();
  const actors_absent: ActorLayerResult["actors_absent"] = [];
  let dynamic_lookups = 0;

  for (const name of candidates) {
    const iaP = lookupInternetArchive(name);
    const caP = lookupChroniclingAmerica(name);
    const ledgerRec = tryResolveActorCandidate(name);
    if (ledgerRec) {
      const [iaEvents, caEvents] = await Promise.all([iaP, caP]);
      const rec = mergeArchiveStack(ledgerRec, iaEvents, caEvents);
      if (!foundBySlug.has(rec.slug)) {
        foundBySlug.set(rec.slug, rec);
      }
    } else {
      const dyn = await dynamicLookupChain(name, { ia: iaP, ca: caP });
      if (dyn) {
        dynamic_lookups++;
        if (!foundBySlug.has(dyn.slug)) {
          foundBySlug.set(dyn.slug, dyn);
        }
      } else {
        actors_absent.push({ name, absent: true, wikidata_attempted: true });
      }
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
    dynamic_lookups,
  };
}
