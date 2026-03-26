/** Canonical citation row for Layer A / B anchoring. */
export interface PrimarySource {
  id: string;
  title: string;
  url: string;
  adapter?: string;
  retrieved_at?: string;
}

export interface VerifiedRecord {
  /** One sentence. Most important confirmed fact. */
  lede: string;
  /** Numbers, dates, parties, amounts in plain language. */
  findings: string;
  /** Specific missing documents named explicitly. */
  gaps: string;
  /** Every claim anchored here. */
  sources: PrimarySource[];
}

export interface ThreadEntry {
  year: number;
  event: string;
  source_url: string;
  source_type: string;
}

export interface HistoricalThread {
  /** First documented instance of this pattern/law/entity. */
  origins: ThreadEntry[];
  /** How it changed over time, who changed it, when. */
  mutations: ThreadEntry[];
  /** Prior instances with documented outcomes. */
  precedents: ThreadEntry[];
  sources: PrimarySource[];
  sourcing_completeness: "full" | "partial" | "inferred";
}

export interface AnalogueEntry {
  period: string;
  description: string;
  /** How it resolved — documented only. */
  outcome: string;
  source_url: string;
}

export interface PatternAnalysis {
  /** Historical comparisons with documented outcomes. */
  analogues: AnalogueEntry[];
  /** Named propaganda/influence techniques where applicable. */
  techniques: string[];
  /** Embedded in hash — cannot be stripped. */
  disclaimer: string;
  /** Every source the inference draws from. */
  inference_basis: string[];
  confidence: "documented" | "probable" | "speculative";
}

export interface ThreeLayerReceiptPayload {
  query: string;
  /** detected: campaign_finance | legislation | judicial | corporate | entity | narrative | unknown */
  query_type: string;
  layer_a: VerifiedRecord;
  layer_b: HistoricalThread;
  layer_c: PatternAnalysis;
  /** The accountability question. Not an answer. */
  why_this_matters: string;
  /** Specific public records a citizen could pull. */
  where_to_look_next: string[];
  content_hash: string;
  signature: string;
  signed: boolean;
  public_key: string;
  generated_at: string;
}
