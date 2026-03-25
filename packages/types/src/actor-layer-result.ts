import type { ActorRecord } from "./actor.js";
import type { ConfidenceTier } from "./depth.js";

/** Narrative-extracted name with no matching ledger row (after slug + exact name/alias attempts). */
export interface ActorAbsentRef {
  name: string;
  absent: true;
  /**
   * True when the dynamic chain (Wikidata → Wikipedia → web inference) ran and returned no row.
   * Name kept for API compatibility.
   */
  wikidata_attempted?: boolean;
}

/** Layer 4 — ledger-backed actors tied to narrative mentions (heuristic extraction). */
export interface ActorLayerResult {
  /** Full ledger rows for resolved slugs. */
  actors_found: ActorRecord[];
  /** Extracted names that did not resolve to a ledger row. */
  actors_absent: ActorAbsentRef[];
  confidence_tier: ConfidenceTier;
  /** Schema gaps (e.g. no candidates, no ledger hits). */
  absent_fields: string[];
  /** Actors resolved via Wikidata / Wikipedia / web inference (non-ledger). */
  dynamic_lookups: number;
}
