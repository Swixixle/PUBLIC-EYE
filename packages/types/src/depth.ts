/**
 * Topographical depth model — six stacked jurisdictions (see DEPTH_LAYERS).
 */

/** Confidence tier labels used in layer rules; orthogonal to processing product tiers. */
export enum ConfidenceTier {
  OfficialPrimary = "official_primary",
  OfficialSecondary = "official_secondary",
  AggregatedRegistry = "aggregated_registry",
  CrossCorroborated = "cross_corroborated",
  SingleSource = "single_source",
  StructuralHeuristic = "structural_heuristic",
}

/** One jurisdictional layer in the depth map. */
export interface DepthLayer {
  layer_number: 1 | 2 | 3 | 4 | 5 | 6;
  layer_name: string;
  contents: string;
  confidence_tiers_allowed: ConfidenceTier[];
  adapter: string;
  depth_available: boolean;
  /** When `depth_available` is false, required non-empty explanation; otherwise null. */
  depth_limit_reason: string | null;
}

/** Thrown when a layer adapter cannot produce depth (infra, policy, or not implemented). */
export class DepthUnavailable extends Error {
  readonly code = "DEPTH_UNAVAILABLE" as const;
  constructor(
    message: string,
    readonly layerNumber: DepthLayer["layer_number"],
  ) {
    super(message);
    this.name = "DepthUnavailable";
  }
}

export const DEPTH_LAYER_SURFACE: DepthLayer = {
  layer_number: 1,
  layer_name: "Surface",
  contents:
    "Public-facing appearances: filings, registries, and crawlable primary pages that establish what is openly asserted without inferring motive.",
  confidence_tiers_allowed: [
    ConfidenceTier.OfficialPrimary,
    ConfidenceTier.OfficialSecondary,
    ConfidenceTier.AggregatedRegistry,
  ],
  adapter: "surface_adapter",
  depth_available: true,
  depth_limit_reason: null,
};

export const DEPTH_LAYER_SPREAD: DepthLayer = {
  layer_number: 2,
  layer_name: "Spread",
  contents:
    "Diffusion and syndication: how statements and documents propagate across outlets, mirrors, and aggregators relative to an anchor record.",
  confidence_tiers_allowed: [
    ConfidenceTier.OfficialSecondary,
    ConfidenceTier.AggregatedRegistry,
    ConfidenceTier.CrossCorroborated,
  ],
  adapter: "spread_adapter",
  depth_available: true,
  depth_limit_reason: null,
};

export const DEPTH_LAYER_ORIGIN: DepthLayer = {
  layer_number: 3,
  layer_name: "Origin",
  contents:
    "Provenance anchors: earliest retrievable artifact, filing identity, and chain-of-custody hints in the public record.",
  confidence_tiers_allowed: [
    ConfidenceTier.OfficialPrimary,
    ConfidenceTier.OfficialSecondary,
    ConfidenceTier.CrossCorroborated,
  ],
  adapter: "origin_adapter",
  depth_available: true,
  depth_limit_reason: null,
};

export const DEPTH_LAYER_ACTOR: DepthLayer = {
  layer_number: 4,
  layer_name: "Actor",
  contents:
    "Named entities and roles: committees, employers, titles, and disclosed relationships as they appear in authoritative or corroborated sources.",
  confidence_tiers_allowed: [
    ConfidenceTier.AggregatedRegistry,
    ConfidenceTier.CrossCorroborated,
    ConfidenceTier.SingleSource,
  ],
  adapter: "actor_adapter",
  depth_available: true,
  depth_limit_reason: null,
};

export const DEPTH_LAYER_PATTERN: DepthLayer = {
  layer_number: 5,
  layer_name: "Pattern",
  contents:
    "Recurrence structure: timing clusters, repeated pairings, and schedule-level regularities constrained to what the record supports.",
  confidence_tiers_allowed: [
    ConfidenceTier.CrossCorroborated,
    ConfidenceTier.SingleSource,
    ConfidenceTier.StructuralHeuristic,
  ],
  adapter: "pattern_adapter",
  depth_available: true,
  depth_limit_reason: null,
};

export const DEPTH_LAYER_JURISDICTION: DepthLayer = {
  layer_number: 6,
  layer_name: "Comparative Jurisdiction",
  contents:
    "Cross-border and non-U.S. registry alignment: comparable disclosures, foreign corporate filings, and treaty-visible instruments when adapters exist.",
  confidence_tiers_allowed: [
    ConfidenceTier.OfficialPrimary,
    ConfidenceTier.CrossCorroborated,
    ConfidenceTier.StructuralHeuristic,
  ],
  adapter: "jurisdiction_adapter",
  depth_available: false,
  depth_limit_reason: "International source adapters not yet built",
};

/** Fixed stack — single source of truth for names, tiers, and adapter wiring. */
export const DEPTH_LAYERS: readonly DepthLayer[] = [
  DEPTH_LAYER_SURFACE,
  DEPTH_LAYER_SPREAD,
  DEPTH_LAYER_ORIGIN,
  DEPTH_LAYER_ACTOR,
  DEPTH_LAYER_PATTERN,
  DEPTH_LAYER_JURISDICTION,
] as const;
