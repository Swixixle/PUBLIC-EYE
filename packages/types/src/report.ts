/**
 * Provenance row for a ring — structurally matches `SourceRecord` (adapter is widened to string for JSON).
 */
export type ReportSourceRow = {
  id: string;
  adapter: string;
  url: string;
  title: string;
  retrievedAt: string;
  externalRef?: string;
  metadata?: Record<string, string | number | boolean | null>;
};

export type ReportUnknownsBlock = {
  operational: Array<{ text: string; resolution_possible: boolean }>;
  epistemic: Array<{ text: string; resolution_possible: boolean }>;
};

/**
 * One ring in the five-ring extended report (surface → spread → origin → actors → patterns).
 * `content` holds the ring-specific adapter payload (SurfaceResult, SpreadResult, etc.).
 */
export interface RingPayload {
  ring: 1 | 2 | 3 | 4 | 5;
  title: string;
  content: Record<string, unknown>;
  confidence_tier: string;
  absent_fields: string[];
  sources: ReportSourceRow[];
}

/**
 * Assembled library-format report: five rings, explicit unknowns, signing hooks (unsigned by default).
 */
export interface ExtendedReportPayload {
  report_id: string;
  generated_at: string;
  narrative: string;
  /** Always length 5, rings 1–5 in order. */
  rings: RingPayload[];
  signed: boolean;
  signature: string | null;
  unknowns: ReportUnknownsBlock;
}
