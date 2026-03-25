import type { ConfidenceTier } from "./depth.js";
import type { SurfaceNamedActor, SurfaceWhenBlock } from "./surface-result.js";

/** Provenance grouping for Layer 4 actor timeline rows (UI + receipts). */
export type ActorSourceCategory =
  | "primary_historical"
  | "academic"
  | "news_archive"
  | "paranormal_community"
  | "dynamic_inference";

/** Single dated fact in an actor's public-record timeline (Layer 4 ledger). */
export interface ActorEvent {
  date: string;
  type: string;
  description: string;
  source: string;
  confidence_tier: ConfidenceTier;
  /** Optional: separates hand-history, archives, community paranormal, and model-derived lines. */
  source_category?: ActorSourceCategory;
}

/** Where a Layer 4 actor row was resolved. Omitted on on-disk ledger JSON. */
export type ActorLookupSource =
  | "ledger"
  | "wikidata"
  | "wikipedia"
  | "web_inference"
  | "internet_archive"
  | "chronicling_america"
  | "mysterious_universe"
  | "anomalist"
  | "cryptomundo"
  | "coast_to_coast"
  | "singular_fortean"
  | "fortean_times";

/** Paranormal/community RSS feeds merged into Layer 4 (deterministic iteration order). */
export const PARANORMAL_RSS_LOOKUP_SOURCES = [
  "mysterious_universe",
  "anomalist",
  "cryptomundo",
  "coast_to_coast",
  "singular_fortean",
  "fortean_times",
] as const;

export type ParanormalRssLookupSource = (typeof PARANORMAL_RSS_LOOKUP_SOURCES)[number];

/** Append-only actor row (events grow at the end only). */
export interface ActorRecord {
  slug: string;
  name: string;
  aliases: string[];
  events: ActorEvent[];
  /** All systems that contributed resolution or stacked events (ledger + dynamic + archives). */
  lookup_source?: ActorLookupSource[] | null;
  /** Wikidata item id (e.g. Q123) when `lookup_source` includes `"wikidata"`. */
  wikidata_id?: string;
  /** MediaWiki title with underscores when `lookup_source` includes `"wikipedia"`. */
  wikipedia_title?: string;
  /**
   * Layer 1 surface pass anchored on Wikidata/Wikipedia text (dynamic rows only).
   */
  what?: string;
  cultural_substrate?: string | null;
  what_confidence_tier?: ConfidenceTier;
  surface_who?: SurfaceNamedActor[];
  surface_when?: SurfaceWhenBlock;
}
