import Anthropic from "@anthropic-ai/sdk";
import type {
  ActorEvent,
  ActorLookupSource,
  ActorSourceCategory,
  DepthLayer,
  ActorLayerResult,
  ActorRecord,
  ParanormalRssLookupSource,
  SourceCheckedEntry,
  SourceCheckedStatus,
} from "@frame/types";
import { PARANORMAL_RSS_LOOKUP_SOURCES } from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_ACTOR } from "@frame/types";
import { lookupInternetArchive } from "./sources/internet-archive.js";
import { lookupChroniclingAmerica } from "./sources/chronicling-america.js";
import { lookupMysteriousUniverse } from "./sources/mysterious-universe.js";
import { lookupAnomalist } from "./sources/anomalist.js";
import { lookupCryptomundo } from "./sources/cryptomundo.js";
import { lookupCoastToCoast } from "./sources/coast-to-coast.js";
import { lookupSingularFortean } from "./sources/singular-fortean.js";
import { lookupForteanTimes } from "./sources/fortean-times.js";
import { lookupJstorOpenAccess } from "./sources/jstor.js";
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
const ADAPTER_MS = 8000;

type WbSnak = {
  snaktype?: string;
  datavalue?: { type?: string; value?: unknown };
};
type WbStatement = {
  mainsnak?: WbSnak;
  references?: Array<{ snaks?: Record<string, WbSnak[]> }>;
};
type WbEntityBody = {
  descriptions?: { en?: { value?: string } };
  sitelinks?: { enwiki?: { title?: string } };
  claims?: Record<string, WbStatement[]>;
};

const RSS_ADAPTER_FN: Record<ParanormalRssLookupSource, (n: string) => Promise<ActorEvent[]>> = {
  mysterious_universe: lookupMysteriousUniverse,
  anomalist: lookupAnomalist,
  cryptomundo: lookupCryptomundo,
  coast_to_coast: lookupCoastToCoast,
  singular_fortean: lookupSingularFortean,
  fortean_times: lookupForteanTimes,
};

function mergeCheckStatus(a: SourceCheckedStatus, b: SourceCheckedStatus): SourceCheckedStatus {
  if (a === "found" || b === "found") return "found";
  if (a === "timeout" || b === "timeout") return "timeout";
  if (a === "error" || b === "error") return "error";
  return "not_found";
}

function isTimeoutErr(e: unknown): boolean {
  return Boolean(e && typeof e === "object" && (e as { code?: string }).code === "timeout");
}

function sleepReject(ms: number): Promise<never> {
  return new Promise((_, rej) =>
    setTimeout(() => rej(Object.assign(new Error("timeout"), { code: "timeout" })), ms),
  );
}

async function runTimed(
  adapter: string,
  fn: () => Promise<ActorEvent[]>,
): Promise<{ events: ActorEvent[]; check: SourceCheckedEntry }> {
  try {
    const events = await Promise.race([fn(), sleepReject(ADAPTER_MS)]);
    return {
      events,
      check: { adapter, status: events.length > 0 ? "found" : "not_found" },
    };
  } catch (e: unknown) {
    return {
      events: [],
      check: {
        adapter,
        status: isTimeoutErr(e) ? "timeout" : "error",
        detail: isTimeoutErr(e) ? undefined : String(e),
      },
    };
  }
}

async function runTimedRecord(
  adapter: string,
  fn: () => Promise<ActorRecord | null>,
): Promise<{ record: ActorRecord | null; check: SourceCheckedEntry }> {
  try {
    const record = await Promise.race([fn(), sleepReject(ADAPTER_MS)]);
    const found = record != null;
    return {
      record,
      check: { adapter, status: found ? "found" : "not_found" },
    };
  } catch (e: unknown) {
    return {
      record: null,
      check: {
        adapter,
        status: isTimeoutErr(e) ? "timeout" : "error",
        detail: isTimeoutErr(e) ? undefined : String(e),
      },
    };
  }
}

type ArchiveStackResult = {
  ia: ActorEvent[];
  ca: ActorEvent[];
  jstor: ActorEvent[];
  rss: Record<ParanormalRssLookupSource, ActorEvent[]>;
  checks: SourceCheckedEntry[];
};

async function runArchiveAndCommunityStack(name: string): Promise<ArchiveStackResult> {
  const [iaR, caR, jstorR, ...rssTimed] = await Promise.all([
    runTimed("internet_archive", () => lookupInternetArchive(name)),
    runTimed("chronicling_america", () => lookupChroniclingAmerica(name)),
    runTimed("jstor", () => lookupJstorOpenAccess(name)),
    ...PARANORMAL_RSS_LOOKUP_SOURCES.map((k) => runTimed(k, () => RSS_ADAPTER_FN[k](name))),
  ]);
  const checks: SourceCheckedEntry[] = [
    iaR.check,
    caR.check,
    jstorR.check,
    ...rssTimed.map((x) => x.check),
  ];
  const rss = Object.fromEntries(
    PARANORMAL_RSS_LOOKUP_SOURCES.map((k, i) => [k, rssTimed[i]!.events]),
  ) as Record<ParanormalRssLookupSource, ActorEvent[]>;
  return {
    ia: iaR.events,
    ca: caR.events,
    jstor: jstorR.events,
    rss,
    checks,
  };
}

const SURFACE_MODEL_DEFAULT_CHAIN = ["claude-haiku-4-5", "claude-3-haiku-20240307"] as const;

function withLedgerPrimaryCategory(rec: ActorRecord): ActorRecord {
  const sources = rec.lookup_source ?? [];
  if (!sources.includes("ledger")) return rec;
  return {
    ...rec,
    events: rec.events.map((e) => ({
      ...e,
      source_category: e.source_category ?? "primary_historical",
    })),
  };
}

function mergeExternalStacks(rec: ActorRecord, stacks: ArchiveStackResult): ActorRecord {
  const base: ActorLookupSource[] = rec.lookup_source ? [...rec.lookup_source] : [];
  const mark = (events: ActorEvent[], src: ActorLookupSource) => {
    if (events.length && !base.includes(src)) base.push(src);
  };
  mark(stacks.ia, "internet_archive");
  mark(stacks.ca, "chronicling_america");
  mark(stacks.jstor, "jstor");
  for (const k of PARANORMAL_RSS_LOOKUP_SOURCES) {
    mark(stacks.rss[k], k);
  }
  const rssExtra = PARANORMAL_RSS_LOOKUP_SOURCES.flatMap((k) => stacks.rss[k]);
  const extra = [...stacks.ia, ...stacks.ca, ...stacks.jstor, ...rssExtra];
  if (extra.length === 0) {
    return { ...rec, lookup_source: base };
  }
  return {
    ...rec,
    lookup_source: base,
    events: [...rec.events, ...extra],
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

function hostLine(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 160);
  }
}

function sourceCategoryFromExternalUrl(url: string): ActorSourceCategory {
  const u = url.toLowerCase();
  if (
    /jstor\.org|\.edu\/|scholar\.google|doi\.org|ncbi\.nlm|arxiv\.org|oecd\.org\/library/.test(u)
  ) {
    return "academic";
  }
  if (
    /cryptomundo|coasttocoastam|forteantimes|mysteriousuniverse|anomalist\.com|singularfortean/.test(
      u,
    )
  ) {
    return "paranormal_community";
  }
  return "primary_historical";
}

function commonsFilePageUrl(filename: string): string {
  const enc = filename.replace(/ /g, "_");
  return `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(enc)}`;
}

function snakUrl(v: unknown): string | null {
  if (typeof v !== "string" || !/^https?:\/\//i.test(v)) return null;
  return v;
}

function collectWikidataLinkedUrls(entity: WbEntityBody): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (u: string | null) => {
    if (!u) return;
    const t = u.trim();
    if (!seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  };
  const p856 = entity.claims?.P856;
  for (const st of p856 ?? []) {
    const v = st.mainsnak?.datavalue?.value;
    push(snakUrl(v));
  }
  const p953 = entity.claims?.P953;
  for (const st of p953 ?? []) {
    const v = st.mainsnak?.datavalue?.value;
    push(snakUrl(v));
  }
  const p18 = entity.claims?.P18;
  for (const st of p18 ?? []) {
    const v = st.mainsnak?.datavalue?.value;
    if (typeof v === "string" && v.trim()) {
      push(commonsFilePageUrl(v.trim()));
    }
  }
  for (const pid of Object.keys(entity.claims ?? {})) {
    for (const stmt of entity.claims?.[pid] ?? []) {
      for (const ref of stmt.references ?? []) {
        for (const snak of ref.snaks?.P854 ?? []) {
          const v = snak.datavalue?.value;
          push(snakUrl(v));
        }
      }
    }
  }
  return out;
}

function shouldExcludeExtLink(url: string): boolean {
  const u = url.toLowerCase();
  return (
    /geohack\.toolforge\.org/.test(u) ||
    /google\.com\/search/.test(u) ||
    /wiktionary\.org/.test(u) ||
    /\/wiki\/geohack/i.test(u)
  );
}

async function resolveEnglishWikipediaTitle(q: string): Promise<string | null> {
  const trimmed = q.trim();
  if (trimmed.length < 2) return null;
  const us = trimmed.replace(/\s+/g, "_");
  try {
    const sum = await fetch(
      `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(us)}`,
      { headers: { "User-Agent": UA } },
    );
    if (sum.ok) {
      const d = (await sum.json()) as { type?: string; title?: string };
      if (d.type !== "disambiguation" && d.title) {
        return d.title.replace(/ /g, "_");
      }
    }
  } catch {
    /* continue to search */
  }
  const searchUrl = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(trimmed)}&srlimit=3&format=json`;
  try {
    const ar = await fetch(searchUrl, { headers: { "User-Agent": UA } });
    if (!ar.ok) return null;
    const ad = (await ar.json()) as {
      query?: { search?: Array<{ title?: string }> };
    };
    const hit = ad.query?.search?.[0]?.title;
    return hit ? hit.replace(/ /g, "_") : null;
  } catch {
    return null;
  }
}

async function fetchWikipediaExtlinks(titleUnderscores: string): Promise<string[]> {
  const t = titleUnderscores.trim();
  if (t.length < 1) return [];
  const api =
    `https://en.wikipedia.org/w/api.php?action=query&titles=${encodeURIComponent(t)}` +
    `&prop=extlinks&ellimit=45&format=json`;
  try {
    const r = await fetch(api, { headers: { "User-Agent": UA } });
    if (!r.ok) return [];
    const d = (await r.json()) as {
      query?: { pages?: Record<string, { extlinks?: Array<{ "*": string }> }> };
    };
    const pages = d.query?.pages ?? {};
    const page = Object.values(pages)[0] as { extlinks?: Array<{ "*": string }> } | undefined;
    const links = (page?.extlinks ?? []).map((x) => x["*"]).filter(Boolean);
    return links.filter((u) => !shouldExcludeExtLink(u)).slice(0, 10);
  } catch {
    return [];
  }
}

function dedupeStrings(xs: string[]): string[] {
  return [...new Set(xs.map((x) => x.trim()).filter(Boolean))];
}

function normalizeSourceKey(s: string): string {
  const t = s.trim().toLowerCase();
  if (/^https?:\/\//i.test(t)) {
    try {
      const u = new URL(t);
      return `${u.hostname}${u.pathname}`.toLowerCase();
    } catch {
      return t;
    }
  }
  return t;
}

function dedupeEventsBySourceUrl(events: ActorEvent[]): ActorEvent[] {
  const seen = new Set<string>();
  const out: ActorEvent[] = [];
  for (const e of events) {
    const key = normalizeSourceKey(e.source || e.description);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

function dedupeLookupSources(sources: ActorLookupSource[]): ActorLookupSource[] {
  return [...new Set(sources)];
}

function mergeDynamicParallelRecords(
  wd: ActorRecord | null,
  wp: ActorRecord | null,
  web: ActorRecord | null,
): ActorRecord | null {
  if (!wd && !wp && !web) return null;
  const name = wd?.name ?? wp?.name ?? web?.name ?? "";
  const slug =
    wd?.slug ??
    wp?.slug ??
    web?.slug ??
    `dyn-${actorNameToSlug(name)}-${shortHash(name)}`;
  return {
    slug,
    name,
    aliases: dedupeStrings([...(wd?.aliases ?? []), ...(wp?.aliases ?? []), ...(web?.aliases ?? [])]),
    lookup_source: dedupeLookupSources([
      ...(wd?.lookup_source ?? []),
      ...(wp?.lookup_source ?? []),
      ...(web?.lookup_source ?? []),
    ]),
    wikidata_id: wd?.wikidata_id,
    wikipedia_title: wp?.wikipedia_title ?? wd?.wikipedia_title,
    events: dedupeEventsBySourceUrl([
      ...(wd?.events ?? []),
      ...(wp?.events ?? []),
      ...(web?.events ?? []),
    ]),
  };
}

async function runParallelResolvers(name: string): Promise<{
  records: { wd: ActorRecord | null; wp: ActorRecord | null; web: ActorRecord | null };
  checks: SourceCheckedEntry[];
}> {
  const [wdR, wpR, webR] = await Promise.all([
    runTimedRecord("wikidata", () => lookupWikidata(name)),
    runTimedRecord("wikipedia_refs", () => lookupWikipediaCitedUrls(name)),
    runTimedRecord("web_inference", () => lookupWeb(name)),
  ]);
  return {
    records: { wd: wdR.record, wp: wpR.record, web: webR.record },
    checks: [wdR.check, wpR.check, webR.check],
  };
}

async function resolveDynamicWithStack(
  name: string,
  stack: ArchiveStackResult,
): Promise<{ record: ActorRecord | null; resolverChecks: SourceCheckedEntry[] }> {
  const { records, checks: resolverChecks } = await runParallelResolvers(name);
  let main = mergeDynamicParallelRecords(records.wd, records.wp, records.web);
  if (main) {
    main = await enrichDynamicRecordWithSurface(main);
    return {
      record: mergeExternalStacks(main, stack),
      resolverChecks,
    };
  }
  const rssExtra = PARANORMAL_RSS_LOOKUP_SOURCES.flatMap((k) => stack.rss[k]);
  const stacked = [...stack.ia, ...stack.ca, ...stack.jstor, ...rssExtra];
  if (stacked.length === 0) {
    return { record: null, resolverChecks };
  }
  const lookup_source: ActorLookupSource[] = [];
  if (stack.ia.length) lookup_source.push("internet_archive");
  if (stack.ca.length) lookup_source.push("chronicling_america");
  if (stack.jstor.length) lookup_source.push("jstor");
  for (const k of PARANORMAL_RSS_LOOKUP_SOURCES) {
    if (stack.rss[k].length) lookup_source.push(k);
  }
  return {
    record: {
      slug: `hist-${actorNameToSlug(name)}-${shortHash(name)}`,
      name,
      aliases: [],
      lookup_source,
      events: stacked,
    },
    resolverChecks,
  };
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
    let refEvents: ActorEvent[] = [];
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
      const entity = ed.entities?.[id] as WbEntityBody | undefined;
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
      if (entity) {
        const linked = collectWikidataLinkedUrls(entity);
        refEvents = linked.slice(0, 24).map((url) => ({
          date: dateStr || "unknown",
          type: "wikidata_reference_url",
          description: `${hostLine(url)} — URL from Wikidata statements or reference qualifiers (P854, P856, P953, P18)`,
          source: url,
          confidence_tier: ConfidenceTier.SingleSource,
          source_category: sourceCategoryFromExternalUrl(url),
        }));
      }
    }

    const anchor: ActorEvent = {
      date: dateStr || "unknown",
      type: "wikidata_anchor",
      description: `${label} — Wikidata ${id}: resolver row only; separate events carry linked URLs.`,
      source: `https://www.wikidata.org/wiki/${id}`,
      confidence_tier: ConfidenceTier.SingleSource,
      source_category: "dynamic_inference",
    };

    return {
      slug: `wd-${id.toLowerCase()}`,
      name: label,
      aliases: q !== label ? [q] : [],
      lookup_source: ["wikidata"],
      wikidata_id: id,
      wikipedia_title,
      events: [...refEvents, anchor],
    };
  } catch {
    return null;
  }
}

/** English Wikipedia: surface external links (extlinks API), not article body as citation. */
export async function lookupWikipediaCitedUrls(name: string): Promise<ActorRecord | null> {
  const q = name.trim();
  if (q.length < 2) return null;
  const title = await resolveEnglishWikipediaTitle(q);
  if (!title) return null;
  const urls = await fetchWikipediaExtlinks(title);
  if (urls.length === 0) return null;
  const pageTitle = title.replace(/_/g, " ");
  const events: ActorEvent[] = urls.map((url) => {
    const ym = url.match(/\b(1[0-9]{3}|20[0-9]{2})\b/);
    return {
      date: ym ? `${ym[1]}-01-01` : "unknown",
      type: "wikipedia_reference_url",
      description: `${hostLine(url)} — external link from Wikipedia extlinks API (article text not used as citation)`,
      source: url,
      confidence_tier: ConfidenceTier.SingleSource,
      source_category: sourceCategoryFromExternalUrl(url),
    };
  });
  return {
    slug: `wiki-ref-${actorNameToSlug(pageTitle)}`,
    name: pageTitle,
    aliases: q.toLowerCase() !== pageTitle.toLowerCase() ? [q] : [],
    lookup_source: ["wikipedia"],
    wikipedia_title: title,
    events,
  };
}

export async function lookupWikipedia(name: string): Promise<ActorRecord | null> {
  return lookupWikipediaCitedUrls(name);
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
        source_category: "dynamic_inference",
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
  const needsSurface = sources.some((s) =>
    ["wikidata", "wikipedia", "web_inference"].includes(s),
  );
  if (!needsSurface) return rec;

  const primaryHints = rec.events
    .filter(
      (e) =>
        e.source_category === "primary_historical" ||
        e.source_category === "academic" ||
        e.type === "wikipedia_reference_url" ||
        e.type === "wikidata_reference_url",
    )
    .map((e) => e.description)
    .filter(Boolean)
    .slice(0, 8);
  const anchorHint =
    (rec.events.find((e) => e.type === "wikidata_anchor")?.description ?? "").trim();
  const parts = [rec.name, ...primaryHints, anchorHint].filter(Boolean);
  let anchorNarrative = parts.join(" ").replace(/\s+/g, " ").trim();
  if (anchorNarrative.length > 0 && !anchorNarrative.endsWith(".")) {
    anchorNarrative += ".";
  }

  let usedWikipediaExtract = false;
  if (sources.includes("wikidata") || sources.includes("wikipedia")) {
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
          ? `Resolver Wikidata ${rec.wikidata_id} + English Wikipedia extract (tertiary context only); Layer 1 surface extraction`
          : `Resolver Wikidata ${rec.wikidata_id}; Layer 1 surface extraction`
        : sources.includes("wikipedia") && rec.wikipedia_title
          ? `Resolver Wikipedia title ${rec.wikipedia_title} (extlinks / tertiary context); Layer 1 surface extraction`
          : "External resolver anchor; Layer 1 surface extraction";
    return {
      ...rec,
      what: surface.what,
      cultural_substrate: surface.cultural_substrate,
      what_confidence_tier: surface.what_confidence_tier,
      surface_who: surface.who,
      surface_when: surface.when,
      events: [
        ...rec.events,
        {
          date: rec.events[0]?.date ?? "unknown",
          type: "layer1_trace",
          description: surface.what,
          source: anchorSource,
          confidence_tier: surface.what_confidence_tier,
          source_category: "dynamic_inference",
        },
      ],
    };
  } catch {
    return rec;
  }
}

/**
 * Full parallel stack (archives + community RSS + resolvers) for a single extracted name.
 * Convenience export for scripts; `getActorLayer` uses `resolveDynamicWithStack` to avoid duplicate fetches.
 */
export async function dynamicLookupChain(name: string): Promise<ActorRecord | null> {
  const stack = await runArchiveAndCommunityStack(name);
  const { record } = await resolveDynamicWithStack(name, stack);
  return record;
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
      if (row) return withLedgerPrimaryCategory({ ...row, lookup_source: ["ledger"] });
    }
    const byName = findActorByExactNameOrAlias(variant);
    if (byName) return withLedgerPrimaryCategory({ ...byName, lookup_source: ["ledger"] });
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
  /** No `/i` on the phrase — with `i`, `[A-Z]` matches lowercase and swallows words like "suburban". */
  const reSight =
    /\b((?:[A-Z][a-z]+\s+){2,}[A-Z][a-z]+)\s+(?:[Ss]ightings|[Rr]eports|[Ll]egend)\b/g;
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

/** Articles / function words — never start a Layer 4 candidate phrase. */
const CAP_PHRASE_REJECT_FIRST = new Set([
  "the",
  "a",
  "an",
  "and",
  "or",
  "but",
  "if",
  "in",
  "on",
  "at",
  "to",
  "for",
  "of",
  "as",
  "is",
  "was",
  "are",
  "it",
  "this",
  "that",
]);

function normalizeWordToken(raw: string): string {
  return raw
    .replace(/^[\[\(""„«'`]+|[\]\)""»'`,;:]+$/g, "")
    .replace(/^[¿¡]+/, "")
    .trim();
}

/**
 * True for tokens that can appear in a capitalized proper-noun run (incl. "St.", "Dr.", "NYC").
 */
function isCapitalizedNameToken(tok: string): boolean {
  if (!tok) return false;
  if (/^[0-9]/.test(tok)) return false;
  if (/^[A-Z]{2,6}$/.test(tok)) return true;
  if (/^[A-Z][a-z]{1,24}\.$/.test(tok)) return true;
  if (/^[A-Z][a-z']+$/.test(tok)) return true;
  return false;
}

function phraseMeetsConfidence(phrase: string): boolean {
  const compact = phrase.replace(/[\s'.]/g, "");
  if (compact.length < 4) return false;
  const lower = phrase.trim().toLowerCase();
  if (CAP_PHRASE_REJECT_FIRST.has(lower)) return false;
  const first = phrase.split(/\s+/)[0]?.toLowerCase() ?? "";
  if (CAP_PHRASE_REJECT_FIRST.has(first)) return false;
  return true;
}

/**
 * Any contiguous run of 1–4 capitalized words in the narrative (no is/was / ledger required).
 * Deduplicated; overlapping phrases are all kept (e.g. "Silver Bridge" and "Point Pleasant" separately).
 */
function capitalizedPhraseExtractor(text: string): string[] {
  const raw = text.trim();
  if (!raw) return [];
  const tokens = raw.split(/\s+/).map(normalizeWordToken).filter(Boolean);
  const out = new Set<string>();

  for (let i = 0; i < tokens.length; i++) {
    if (!isCapitalizedNameToken(tokens[i]!)) continue;
    for (let len = 1; len <= 4 && i + len <= tokens.length; len++) {
      const slice = tokens.slice(i, i + len);
      if (!slice.every((w) => isCapitalizedNameToken(w!))) break;
      const phrase = slice.join(" ");
      if (!phraseMeetsConfidence(phrase)) continue;
      out.add(phrase);
    }
  }
  return [...out];
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
  for (const x of capitalizedPhraseExtractor(text)) {
    if (x.trim()) set.add(x.trim());
  }
  return [...set].sort((a, b) => a.localeCompare(b));
}

/** Capitalized 1–4 word phrases only (Layer 4 helper); exported for tests. */
export function extractCapitalizedPhraseCandidates(text: string): string[] {
  return capitalizedPhraseExtractor(text);
}

/** Full Layer 4 candidate merge (tests / diagnostics). */
export function mergeLayer4Candidates(text: string): string[] {
  return mergeCandidates(text);
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
  const checkAgg = new Map<string, SourceCheckedStatus>();

  const addChecks = (entries: SourceCheckedEntry[]) => {
    for (const e of entries) {
      const prev = checkAgg.get(e.adapter);
      checkAgg.set(e.adapter, prev ? mergeCheckStatus(prev, e.status) : e.status);
    }
  };

  for (const name of candidates) {
    const stack = await runArchiveAndCommunityStack(name);
    addChecks(stack.checks);
    const ledgerRec = tryResolveActorCandidate(name);
    if (ledgerRec) {
      const rec = mergeExternalStacks(ledgerRec, stack);
      if (!foundBySlug.has(rec.slug)) {
        foundBySlug.set(rec.slug, rec);
      }
    } else {
      const { record, resolverChecks } = await resolveDynamicWithStack(name, stack);
      addChecks(resolverChecks);
      if (record) {
        dynamic_lookups++;
        if (!foundBySlug.has(record.slug)) {
          foundBySlug.set(record.slug, record);
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

  const sources_checked = [...checkAgg.entries()]
    .map(([adapter, status]) => ({ adapter, status }))
    .sort((a, b) => a.adapter.localeCompare(b.adapter));

  return {
    actors_found,
    actors_absent,
    confidence_tier,
    absent_fields,
    dynamic_lookups,
    sources_checked,
  };
}
