import type { ConfidenceTier } from "./depth.js";

/** Single dated fact in an actor's public-record timeline (Layer 4 ledger). */
export interface ActorEvent {
  date: string;
  type: string;
  description: string;
  source: string;
  confidence_tier: ConfidenceTier;
}

/** Where a Layer 4 actor row was resolved. Omitted on on-disk ledger JSON. */
export type ActorLookupSource = "ledger" | "wikidata" | "wikipedia" | "web_inference";

/** Append-only actor row (events grow at the end only). */
export interface ActorRecord {
  slug: string;
  name: string;
  aliases: string[];
  events: ActorEvent[];
  lookup_source?: ActorLookupSource | null;
  /** Wikidata item id (e.g. Q123) when `lookup_source === "wikidata"`. */
  wikidata_id?: string;
  /** MediaWiki title with underscores when `lookup_source === "wikipedia"`. */
  wikipedia_title?: string;
}
