/** Lifecycle for a pattern-match dispute (credibility gate). */
export type DisputeStatus = "RECEIVED" | "UNDER_REVIEW" | "RESOLVED";

export interface DisputeEntry {
  dispute_id: string;
  pattern_id: string;
  submitted_at: string;
  counter_evidence: string;
  submitter_note: string | null;
  status: DisputeStatus;
  resolution_note: string | null;
}
