import type { ConfidenceTier } from "./depth.js";

/**
 * Layer 3 (Origin) — heuristic first-instance / provenance signals from narrative text only.
 */
export interface OriginResult {
  /** Phrases suggesting an earliest-known or traced origin. */
  first_instance_indicators: string[];
  /** Named people, venues, or sites in origin-framed context (heuristic). */
  seeding_actors: string[];
  /** True when copy supports a dateable first instance with a concrete hook (person, venue, or similar). */
  anchor_exists: boolean;
  /** One-sentence read of the claimed anchor, or null if none. */
  anchor_description: string | null;
  confidence_tier: ConfidenceTier;
  /** Fields that could not be grounded from the narrative. */
  absent_fields: string[];
}
