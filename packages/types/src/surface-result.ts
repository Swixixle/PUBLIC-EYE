import type { ConfidenceTier } from "./depth.js";

/** Named entity as surfaced from the input (Layer 1). */
export interface SurfaceNamedActor {
  name: string;
  confidence_tier: ConfidenceTier;
}

/** Earliest datable appearance described in the material. */
export interface SurfaceWhenBlock {
  earliest_appearance: string;
  source: string;
  confidence_tier: ConfidenceTier;
}

/**
 * Layer 1 (Surface) extraction — structured only; no free-form assistant prose outside `what`.
 */
export interface SurfaceResult {
  what: string;
  what_confidence_tier: ConfidenceTier;
  who: SurfaceNamedActor[];
  when: SurfaceWhenBlock;
  /** Present when the request used a URL input; otherwise null. */
  source_url: string | null;
  /** Tier for URL resolution/identity; null when `source_url` is null. */
  source_url_confidence_tier: ConfidenceTier | null;
  /**
   * Keys among: what, who, when, source_url — that could not be populated from the input.
   * Always present; empty only when every field was populated (fully traced surface).
   */
  absent_fields: string[];
}

export type SurfaceLayerInput =
  | { narrative: string; url?: undefined }
  | { url: string; narrative?: undefined };
