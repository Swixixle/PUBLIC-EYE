/**
 * Frame — shared TypeScript types for receipts, sources, narrative, and entities.
 */

/** Identifies a row in the `sources` array; every narrative sentence must reference one. */
export type SourceId = string;

/** Supported upstream systems (adapters). */
export type SourceAdapterKind =
  | "fec"
  | "opensecrets"
  | "propublica"
  | "lobbying"
  | "edgar"
  | "manual"
  | "congress"
  | "wikidata";

/** A verifiable document or API-backed citation. */
export interface SourceRecord {
  id: SourceId;
  adapter: SourceAdapterKind;
  /** HTTPS URL when available; may be a stable API permalink. */
  url: string;
  /** Human-readable label for UI. */
  title: string;
  /** ISO 8601 timestamp when Frame retrieved or normalized the record. */
  retrievedAt: string;
  /** Optional opaque pointer (e.g. committee id, filing accession). */
  externalRef?: string;
  /** Structured fields per adapter (amounts, committee names, etc.). */
  metadata?: Record<string, string | number | boolean | null>;
}

/** One sentence in the public narrative; must cite `sourceId`. */
export interface NarrativeSentence {
  text: string;
  sourceId: SourceId;
}

/** One limit or gap: operational (may resolve with better infra) vs epistemic (cannot in principle). */
export interface UnknownItem {
  text: string;
  resolution_possible: boolean;
}

/** Split unknowns — evidence boundaries, not a flat string list. */
export interface UnknownsBlock {
  operational: UnknownItem[];
  epistemic: UnknownItem[];
}

export function emptyUnknowns(): UnknownsBlock {
  return { operational: [], epistemic: [] };
}

export function opUnknown(text: string): UnknownItem {
  return { text, resolution_possible: true };
}

export function epiUnknown(text: string): UnknownItem {
  return { text, resolution_possible: false };
}

export function mergeUnknowns(a: UnknownsBlock, b: UnknownsBlock): UnknownsBlock {
  return {
    operational: [...a.operational, ...b.operational],
    epistemic: [...a.epistemic, ...b.epistemic],
  };
}

/** Risk that readers infer more than the public record supports. */
export type ImplicationRisk = "low" | "medium" | "high";

/** How the claim relates to observation vs inference (schema-level, not prose). */
export type ClaimEvidenceType = "observed" | "inferred" | "unknown";

/** High-level claim being framed (neutral wording expected by governance). */
export interface ClaimRecord {
  id: string;
  /** Short neutral summary of the claim under review. */
  statement: string;
  /** ISO 8601 when the claim was observed or filed. */
  assertedAt?: string;
  type: ClaimEvidenceType;
  implication_risk: ImplicationRisk;
  /** Required when `implication_risk` is `high` — deterministic boundary, signed into the receipt. */
  implication_note?: string;
}

/**
 * Build a claim object; throws if `high` risk is given without `implication_note`.
 * Uses `statement` (Frame's field name) — not renamed to `text` — for signing compatibility.
 */
export function buildClaim(
  id: string,
  statement: string,
  type: ClaimEvidenceType,
  risk: ImplicationRisk,
  assertedAt: string | undefined,
  implicationNote?: string,
): ClaimRecord {
  if (risk === "high" && (implicationNote == null || implicationNote === "")) {
    throw new Error(
      `Claim with implication_risk 'high' requires an implication_note. Claim: "${statement}"`,
    );
  }
  const base: ClaimRecord = {
    id,
    statement,
    assertedAt,
    type,
    implication_risk: risk,
  };
  if (risk === "high" && implicationNote) {
    return { ...base, implication_note: implicationNote };
  }
  return base;
}

export { IMPLICATION_NOTES, getImplicationNote, type EvidenceCategory } from "./implication-notes.js";

/** Entity as returned from resolver / external graph. */
export interface EntityCandidate {
  id: string;
  label: string;
  /** 0..1 confidence from the disambiguation step. */
  score: number;
  /** Optional type hint (person, committee, organization). */
  kind?: "person" | "committee" | "organization" | "unknown";
}

export interface DisambiguationResult {
  query: string;
  chosen?: EntityCandidate;
  alternatives: EntityCandidate[];
  /** True when `chosen` meets the configured confidence floor. */
  meetsFloor: boolean;
}

/** Payload signed by Frame (fields that participate in JCS hashing exclude `signature`). */
export interface FrameReceiptPayload {
  /** Semantic version of the receipt schema. */
  schemaVersion: "1.0.0";
  /** Unique receipt identifier (UUID recommended). */
  receiptId: string;
  /** ISO 8601 creation time. */
  createdAt: string;
  claims: ClaimRecord[];
  sources: SourceRecord[];
  narrative: NarrativeSentence[];
  /**
   * What remains unknown or limited: operational (timeouts, rate limits, missing keys)
   * vs epistemic (intent, causation, absence of proof in public record).
   */
  unknowns: UnknownsBlock;
  /** SHA-256 (hex) of the JCS-canonical unsigned payload. */
  contentHash: string;
  /** Optional public key hint (SPKI PEM or base64) for verification UX. */
  signerPublicKey?: string;
}

/** Full receipt including cryptographic signature (hex: 128 chars for Ed25519 raw or encoding-specific). */
export interface FrameSignedReceipt extends FrameReceiptPayload {
  /** Base64-encoded Ed25519 signature over SHA-256(JCS(unsigned)). */
  signature: string;
  /** Base64-encoded SPKI DER of the public key (matches Node key export). */
  publicKey: string;
}

/** Adapter query shape (normalized across providers). */
export interface SourceQuery {
  kind: SourceAdapterKind;
  /** Free-text or structured per adapter. */
  params: Record<string, string | number | boolean | undefined>;
}

export interface SourceAdapterResult {
  sources: SourceRecord[];
  /** Adapter-reported errors (network, rate limit). */
  errors?: string[];
  /** Optional structured adapter output (e.g. for live receipt builders). */
  metadata?: Record<string, unknown>;
}

export type SourceAdapter = (query: SourceQuery) => Promise<SourceAdapterResult>;

/** Governance / validation issue codes. */
export type NarrativeViolationCode =
  | "MISSING_SOURCE_ID"
  | "UNKNOWN_SOURCE_ID"
  | "BANNED_LANGUAGE"
  | "DOMAIN_NOT_WHITELISTED";

export interface NarrativeViolation {
  code: NarrativeViolationCode;
  message: string;
  /** Index in `narrative` when applicable. */
  sentenceIndex?: number;
  /** Matched token when applicable. */
  token?: string;
}
