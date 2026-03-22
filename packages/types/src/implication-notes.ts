/**
 * Deterministic implication boundaries — one sentence per category, not LLM output.
 */
export type EvidenceCategory =
  | "campaign_finance"
  | "lobbying"
  | "paid_advertising"
  | "nonprofit_financials"
  | "media_hash"
  | "ai_detection"
  | "affiliation"
  | "cross_reference";

export const IMPLICATION_NOTES: Record<EvidenceCategory, string> = {
  campaign_finance:
    "Campaign finance totals reflect disclosed contributions and expenditures; they do not establish improper conduct, quid pro quo, or policy influence.",
  lobbying:
    "Lobbying filings reflect registered activity; they do not establish that legislative outcomes were influenced or that any coordination occurred.",
  paid_advertising:
    "Paid advertising presence reflects disclosed spend; it does not establish the purpose, effectiveness, or authorship of the content.",
  nonprofit_financials:
    "990 data reflects IRS-filed financials; it does not establish fraud, misuse, or improper relationships.",
  media_hash:
    "A cryptographic hash proves file identity at observation time; it does not establish the truth or falsity of any claims within the file.",
  ai_detection:
    "AI detection scores reflect model output probabilities; they do not constitute a determination that content is or is not AI-generated.",
  affiliation:
    "Documented affiliations reflect public records; they do not establish that the subject acted on behalf of any affiliated entity.",
  cross_reference:
    "Co-occurrence in public records does not establish coordination, causation, or shared intent between the referenced entities.",
};

export function getImplicationNote(category: EvidenceCategory): string {
  return IMPLICATION_NOTES[category];
}
