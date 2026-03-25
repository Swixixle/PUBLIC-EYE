import type { FrameReceiptPayload, ImplicationRisk } from "@frame/types";
import { buildClaim, epiUnknown, getImplicationNote, opUnknown } from "@frame/types";
import { createHash, randomUUID } from "node:crypto";
import { loadFramePrivateKeyFromEnv, signReceipt } from "../packages/signing/dist/index.js";

const privateKey = loadFramePrivateKeyFromEnv();

/** Matches SourceRecord.metadata contract from analyze-media / _verify_and_snapshot_source */
type VerificationMeta = {
  verificationStatus: "verified" | "unverified";
  suggestedBy?: "claude";
  requestedUrl: string;
  finalUrl: string | null;
  httpStatus: number | null;
  contentHash: string | null;
  pageTitle: string | null;
  retrievedAt: string | null;
  reason: string | null;
};

type ClaimPrimarySource = {
  label?: string;
  url?: string;
  type?: string;
  verification?: VerificationMeta;
};
type AdapterResultRow = {
  adapter?: string;
  data?: Record<string, unknown> | null;
  error?: string | null;
};

type ClaimObj = {
  text?: string;
  type?: string;
  entities?: string[];
  primary_sources?: ClaimPrimarySource[];
  adapterResults?: AdapterResultRow[];
  timestamp_start?: number;
  timestamp_end?: number;
  speaker?: string;
};

function claimSourceId(url: string): string {
  return `claim-src-${createHash("sha256").update(url).digest("hex").slice(0, 16)}`;
}

function adapterResultId(ar: AdapterResultRow): string {
  const a = (ar.adapter || "manual").toLowerCase();
  return `adapter-${a}-${createHash("sha256").update(JSON.stringify(ar)).digest("hex").slice(0, 16)}`;
}

function mapAdapterKind(name: string): FrameReceiptPayload["sources"][number]["adapter"] {
  const n = (name || "").toLowerCase();
  if (n === "fec") return "fec";
  if (n === "irs990") return "propublica";
  if (n === "lda") return "lobbying";
  if (n === "congress") return "congress";
  if (n === "wikidata") return "wikidata";
  return "manual";
}

function adapterResultUrl(ar: AdapterResultRow): string {
  const d = ar.data as Record<string, unknown> | undefined;
  if (d && typeof d.sourceUrl === "string") return d.sourceUrl;
  if (d && typeof d.searchUrl === "string") return d.searchUrl as string;
  return `https://frame.invalid/adapter/${(ar.adapter || "unknown").replace(/\W/g, "-")}`;
}

function adapterResultTitle(ar: AdapterResultRow): string {
  const d = ar.data as Record<string, unknown> | undefined;
  if (d && typeof d.summary === "string") return d.summary;
  if (ar.error) return `${ar.adapter || "adapter"} error: ${ar.error.slice(0, 120)}`;
  return `${ar.adapter || "adapter"} — public record lookup`;
}

function buildMetadata(ps: ClaimPrimarySource, v: VerificationMeta | undefined): Record<string, string | number | boolean | null> {
  if (!v) {
    return {
      verificationStatus: "unverified",
      suggestedBy: "claude",
      requestedUrl: String(ps.url ?? ""),
      finalUrl: null,
      httpStatus: null,
      contentHash: null,
      pageTitle: null,
      retrievedAt: null,
      reason: "fetch_failed",
    };
  }
  return {
    verificationStatus: v.verificationStatus,
    suggestedBy: v.suggestedBy ?? "claude",
    requestedUrl: v.requestedUrl,
    finalUrl: v.finalUrl ?? null,
    httpStatus: v.httpStatus ?? null,
    contentHash: v.contentHash ?? null,
    pageTitle: v.pageTitle ?? null,
    retrievedAt: v.retrievedAt ?? null,
    reason: v.reason ?? null,
  };
}

const input = JSON.parse(
  await new Promise<string>((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
  }),
) as {
  fileHash: string;
  fileName: string;
  fileSize: number;
  contentType: string;
  detection: {
    detector?: string;
    ai_generated_score?: number | null;
    error?: string;
    note?: string;
    classes?: unknown[];
  };
  timestamp: string;
  perceptualHash?: string | null;
  perceptualHashType?: string | null;
  extractedText?: string | null;
  extractedClaims?: string[];
  extractedClaimObjects?: ClaimObj[];
  ledgerMatch?: Record<string, unknown> | null;
  claimText?: string | null;
  sourceType?: string | null;
  sourceUrl?: string | null;
  podcastTitle?: string | null;
  transcript?: {
    segments?: Array<{ start?: number; end?: number; text?: string }>;
    full_text?: string;
    duration?: number;
  } | null;
  /** Tesseract OCR result from analyze-media (Task 2.1) */
  ocr?: Record<string, unknown> | null;
};

function formatTs(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return [h, m, ss].map((n) => String(n).padStart(2, "0")).join(":");
}

const aiScore = input.detection?.ai_generated_score;
const detectorName = input.detection?.detector ?? "unknown";
const hasDetection = aiScore != null && typeof aiScore === "number";
const perceptualHash = input.perceptualHash ?? null;
const extractedClaims: string[] = input.extractedClaims ?? [];
const claimObjects: ClaimObj[] = input.extractedClaimObjects ?? [];
const extractedText: string = input.extractedText ?? "";
const ledgerMatch = input.ledgerMatch ?? null;

const sourceId = `media-${(input.fileHash as string).slice(0, 16)}`;
const isPodcast = input.sourceType === "podcast";

const narrativeSentences: Array<{ text: string; sourceId: string }> = [];

if (isPodcast) {
  const src = input.sourceUrl ?? "upload";
  const segCount = input.transcript?.segments?.length ?? 0;
  const dur = Math.round(input.transcript?.duration ?? 0);
  narrativeSentences.push({
    text: `Podcast/video analysis at ${input.timestamp}: "${input.podcastTitle || input.fileName}" (${input.contentType}, ${input.fileSize} bytes). Acoustic fingerprint SHA-256: ${input.fileHash}. Source: ${src}.`,
    sourceId,
  });
  narrativeSentences.push({
    text: `Whisper (base) transcription: ${segCount} segments, duration ${dur}s. Perceptual image hash and image AI-detection do not apply to audio.`,
    sourceId,
  });
  narrativeSentences.push({
    text: `Ledger: Perceptual-hash viral ledger is image-only; this receipt is anchored to the acoustic fingerprint and transcript below.`,
    sourceId,
  });
} else {
  // Sentence 1 — cryptographic identity
  narrativeSentences.push({
    text: `At ${input.timestamp}, media file "${input.fileName}" (${input.contentType}, ${input.fileSize} bytes) was received and cryptographically hashed. SHA-256: ${input.fileHash}.`,
    sourceId,
  });

  // Sentence 2 — perceptual fingerprint
  if (perceptualHash) {
    narrativeSentences.push({
      text: `Perceptual fingerprint (pHash-DCT-64bit): ${perceptualHash}. This fingerprint remains stable across re-compression, watermarking, and minor cropping, enabling identification of near-duplicate copies across platforms.`,
      sourceId,
    });
  }

  // Sentence 3 — prior appearance / ledger match
  if (ledgerMatch) {
    const msg = String(ledgerMatch.message ?? "");
    const mt = String(ledgerMatch.matchType ?? "");
    const hd = ledgerMatch.hammingDistance;
    narrativeSentences.push({
      text: `Ledger check: ${msg} Match type: ${mt}${hd != null ? ` (Hamming distance: ${String(hd)}/64)` : ""}.`,
      sourceId,
    });
  } else {
    narrativeSentences.push({
      text: `Ledger check: No prior record of this content found at time of signing. This receipt establishes the first-seen timestamp.`,
      sourceId,
    });
  }

  // Sentence 4 — AI detection
  if (hasDetection) {
    narrativeSentences.push({
      text: `AI-generated content detection (${detectorName}): ${((aiScore as number) * 100).toFixed(1)}% probability of AI generation.`,
      sourceId,
    });
  } else {
    narrativeSentences.push({
      text: `AI-generated content detection: No detector configured at time of signing. Set HIVE_API_KEY in environment to enable.`,
      sourceId,
    });
  }

  // Sentence 5 — extracted text
  if (extractedText && extractedText.length > 0 && !extractedText.startsWith("OCR unavailable")) {
    narrativeSentences.push({
      text: `OCR text extraction: "${extractedText.slice(0, 500)}${extractedText.length > 500 ? "..." : ""}"`,
      sourceId,
    });
  }
}

const claimsForNarrative =
  claimObjects.length > 0
    ? claimObjects
    : extractedClaims.map((t) => ({
        text: t,
        type: "general",
        entities: [] as string[],
        primary_sources: [] as ClaimPrimarySource[],
      }));

// One sentence per claim — podcast uses timestamp + speaker attribution
for (const claim of claimsForNarrative.slice(0, 5)) {
  const c = claim as ClaimObj;
  const claimText = typeof claim === "string" ? claim : (claim.text ?? "");
  if (isPodcast) {
    const ts =
      typeof c.timestamp_start === "number" ? formatTs(c.timestamp_start) : "??:??:??";
    const sp = (c.speaker || "speaker").replace(/"/g, "'");
    const ent = (c.entities || []).join(", ");
    narrativeSentences.push({
      text: `At ${ts}, ${sp} said: "${(c.text ?? "").slice(0, 400)}" [${c.type ?? "general"} · ${ent}]`,
      sourceId,
    });
  } else {
    narrativeSentences.push({
      text: `Extracted claim (${(claim as ClaimObj).type ?? "general"}): "${claimText}"`,
      sourceId,
    });
  }
}

// Verified primary sources only — each cite its own source row id
for (const claim of claimsForNarrative.slice(0, 5)) {
  for (const ps of (claim.primary_sources ?? []).slice(0, 3)) {
    if (!ps.url || !ps.label) continue;
    const v = ps.verification as VerificationMeta | undefined;
    const sid = claimSourceId(String(ps.url));
    if (v?.verificationStatus === "verified" && v.contentHash) {
      narrativeSentences.push({
        text: `Verified primary source at signing time: ${ps.label} — content SHA-256 ${String(v.contentHash).slice(0, 16)}… (${v.finalUrl || v.requestedUrl})`,
        sourceId: sid,
      });
    }
  }
}

// Gap 3 — router-driven public record adapters (FEC, 990, LDA, Congress, Wikidata)
for (const claim of claimsForNarrative.slice(0, 5)) {
  const ars = (claim as ClaimObj).adapterResults ?? [];
  for (const ar of ars.slice(0, 5)) {
    const sid = adapterResultId(ar);
    narrativeSentences.push({
      text: `Public record (${ar.adapter ?? "adapter"}): ${adapterResultTitle(ar)}`,
      sourceId: sid,
    });
  }
}

const firstClaimText =
  claimObjects.length > 0 && claimObjects[0].text
    ? claimObjects[0].text!.slice(0, 100)
    : extractedClaims[0]?.slice(0, 100) ?? "";
const claimStatement = firstClaimText
  ? isPodcast
    ? `Podcast/video: "${firstClaimText}" — acoustic ${(input.fileHash as string).slice(0, 16)}...`
    : `Media analysis: "${firstClaimText}" — file ${(input.fileHash as string).slice(0, 16)}...`
  : isPodcast
    ? `Podcast/video transcript receipt — acoustic SHA-256: ${(input.fileHash as string).slice(0, 16)}...`
    : `Media file integrity receipt — SHA-256: ${(input.fileHash as string).slice(0, 16)}...`;

const hasOcrText =
  !isPodcast &&
  extractedText.trim().length > 0 &&
  !extractedText.startsWith("OCR unavailable");

let implicationRisk: ImplicationRisk = "low";
let implicationNote: string | undefined;
if (hasDetection) {
  implicationRisk = "high";
  implicationNote = getImplicationNote("ai_detection");
} else if (hasOcrText) {
  implicationRisk = "medium";
}

const claimSources: FrameReceiptPayload["sources"] = [];
for (const claim of claimObjects.slice(0, 5)) {
  for (const ps of (claim.primary_sources ?? []).slice(0, 3)) {
    if (!ps.url || !ps.label) continue;
    const v = ps.verification as VerificationMeta | undefined;
    const sid = claimSourceId(String(ps.url));
    const meta = buildMetadata(ps, v);
    const displayUrl =
      v?.verificationStatus === "verified" && v.finalUrl ? v.finalUrl : String(ps.url);
    claimSources.push({
      id: sid,
      adapter: "manual",
      url: displayUrl,
      title: ps.label,
      retrievedAt:
        v?.verificationStatus === "verified" && v.retrievedAt ? v.retrievedAt : input.timestamp,
      externalRef: v?.requestedUrl ?? String(ps.url),
      metadata: meta as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>,
    });
  }
  for (const ar of ((claim as ClaimObj).adapterResults ?? []).slice(0, 5)) {
    const sid = adapterResultId(ar);
    const d = ar.data as Record<string, unknown> | null | undefined;
    const dataErr = d && typeof d === "object" && d.error != null && d.error !== "";
    const verified = !ar.error && ar.data != null && !dataErr;
    const url = adapterResultUrl(ar);
    const title = adapterResultTitle(ar);
    const meta = {
      verificationStatus: verified ? "verified" : "unverified",
      suggestedBy: "router",
      requestedUrl: url,
      finalUrl: verified ? url : null,
      httpStatus: verified ? 200 : null,
      contentHash: null,
      pageTitle: null,
      retrievedAt: null,
      reason: ar.error ?? null,
      adapterData: JSON.stringify(ar.data ?? {}),
    };
    claimSources.push({
      id: sid,
      adapter: mapAdapterKind(ar.adapter ?? "manual"),
      url,
      title,
      retrievedAt: input.timestamp,
      externalRef: ar.adapter ?? "adapter",
      metadata: meta as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>,
    });
  }
}

const transcriptRowId = `transcript-${createHash("sha256").update(`${input.fileHash}:transcript`).digest("hex").slice(0, 16)}`;
const transcriptSource: FrameReceiptPayload["sources"][number] | null = isPodcast
  ? {
      id: transcriptRowId,
      adapter: "manual",
      url: `whisper://local/${input.fileHash}`,
      title: `Whisper transcript: ${input.podcastTitle || input.fileName}`,
      retrievedAt: input.timestamp,
      externalRef: (input.sourceUrl ?? "upload") as string,
      metadata: {
        model: "whisper-base",
        duration: input.transcript?.duration ?? 0,
        segmentCount: input.transcript?.segments?.length ?? 0,
        sourceUrl: input.sourceUrl,
        sourceType: "podcast",
      } as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>,
    }
  : null;

const mainMetadata = (
  isPodcast
    ? {
        sourceType: "podcast",
        fileHash: input.fileHash,
        fileName: input.fileName,
        fileSize: input.fileSize,
        contentType: input.contentType,
        sourceUrl: input.sourceUrl,
        podcastTitle: input.podcastTitle,
        detection: input.detection,
        transcriptSegmentCount: input.transcript?.segments?.length ?? 0,
        extractedClaimsCount: extractedClaims.length,
      }
    : {
        fileHash: input.fileHash,
        perceptualHash: perceptualHash,
        perceptualHashType: input.perceptualHashType,
        fileName: input.fileName,
        fileSize: input.fileSize,
        contentType: input.contentType,
        detection: input.detection,
        ocr: input.ocr ?? null,
        ledgerMatch: ledgerMatch,
        extractedClaimsCount: extractedClaims.length,
      }
) as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>;

const operationalUnknowns = [];
if (isPodcast) {
  operationalUnknowns.push(
    opUnknown(
      "Long-form audio may be trimmed to the configured maximum duration (30 minutes in v1). Whisper transcription may time out on very long jobs.",
    ),
  );
}
if (!hasDetection && !isPodcast) {
  operationalUnknowns.push(
    opUnknown(
      "AI-generated content detection was not configured at signing time (HIVE_API_KEY).",
    ),
  );
}
if (extractedText.startsWith("OCR unavailable")) {
  operationalUnknowns.push(
    opUnknown("OCR vision pipeline was unavailable or failed at signing time."),
  );
}

const payload: FrameReceiptPayload = {
  schemaVersion: "1.0.0",
  receiptId: randomUUID(),
  createdAt: input.timestamp,
  claims: [
    buildClaim(
      "claim-1",
      claimStatement,
      "observed",
      implicationRisk,
      input.timestamp,
      implicationNote,
    ),
  ],
  unknowns: {
    operational: operationalUnknowns,
    epistemic: [
      epiUnknown(
        "This receipt documents what was observed and retrieved from cited sources; it does not independently establish the truth of any claim or image.",
      ),
      ...(isPodcast
        ? [
            epiUnknown(
              "Transcript and claim extraction rely on model inference; they are not prima facie proof of what was said or meant.",
            ),
          ]
        : []),
      epiUnknown(
        "Suggested primary source URLs may not resolve, may omit context, or may reflect summaries rather than primary records.",
      ),
    ],
  },
  sources: [
    {
      id: sourceId,
      adapter: "manual",
      url: `sha256:${input.fileHash}`,
      title: isPodcast
        ? `Podcast/video: ${input.podcastTitle || input.fileName} (${input.contentType})`
        : `Media file: ${input.fileName} (${input.contentType})`,
      retrievedAt: input.timestamp,
      externalRef: input.fileHash as string,
      metadata: mainMetadata,
    },
    ...(transcriptSource ? [transcriptSource] : []),
    ...claimSources,
  ],
  narrative: narrativeSentences,
  contentHash: "",
};

const signed = signReceipt(payload, { privateKey });
process.stdout.write(`${JSON.stringify(signed)}\n`);
