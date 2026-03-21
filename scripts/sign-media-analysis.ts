import type { FrameReceiptPayload } from "@frame/types";
import { createHash, createPrivateKey, randomUUID } from "node:crypto";
import { signReceipt } from "../packages/signing/index.js";

type ClaimPrimarySource = {
  label?: string;
  url?: string;
  type?: string;
  verification?: Record<string, unknown>;
};
type ClaimObj = {
  text?: string;
  type?: string;
  entities?: string[];
  primary_sources?: ClaimPrimarySource[];
};

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
};

function getPrivateKeyPem(): string {
  const format = process.env.FRAME_KEY_FORMAT ?? "pem";
  const raw = process.env.FRAME_PRIVATE_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PRIVATE_KEY");
  if (format === "base64") {
    const decoded = Buffer.from(raw.trim(), "base64").toString("utf8");
    return decoded.replace(/\\n/g, "\n");
  }
  return raw.replace(/\\n/g, "\n").replace(/^["']|["']$/g, "").trim();
}

const privateKey = createPrivateKey(getPrivateKeyPem());

const aiScore = input.detection?.ai_generated_score;
const detectorName = input.detection?.detector ?? "unknown";
const hasDetection = aiScore != null && typeof aiScore === "number";
const perceptualHash = input.perceptualHash ?? null;
const extractedClaims: string[] = input.extractedClaims ?? [];
const claimObjects: ClaimObj[] = input.extractedClaimObjects ?? [];
const extractedText: string = input.extractedText ?? "";
const ledgerMatch = input.ledgerMatch ?? null;

const sourceId = `media-${(input.fileHash as string).slice(0, 16)}`;

const narrativeSentences: Array<{ text: string; sourceId: string }> = [];

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

// Sentences 6+ — extracted claims (with classification and primary sources)
const claimsForNarrative =
  claimObjects.length > 0
    ? claimObjects
    : extractedClaims.map((t) => ({
        text: t,
        type: "general",
        entities: [] as string[],
        primary_sources: [] as ClaimPrimarySource[],
      }));

for (const claim of claimsForNarrative.slice(0, 5)) {
  const claimText = typeof claim === "string" ? claim : (claim.text ?? "");
  const sources = (claim as ClaimObj).primary_sources ?? [];
  const sourceList = sources
    .map((s) => {
      const ver = (s as ClaimPrimarySource).verification;
      const tail =
        ver?.verified && ver.contentHash
          ? ` [verified SHA-256: ${String(ver.contentHash).slice(0, 12)}…]`
          : ver?.error || ver?.note
            ? ` [${String(ver.error || ver.note)}]`
            : "";
      return `${s.label}: ${s.url}${tail}`;
    })
    .filter(Boolean)
    .join(" | ");
  narrativeSentences.push({
    text: `Extracted claim (${(claim as ClaimObj).type ?? "general"}): "${claimText}"${sourceList ? ` — Primary sources: ${sourceList}` : ""}`,
    sourceId,
  });
}

const firstClaimText =
  claimObjects.length > 0 && claimObjects[0].text
    ? claimObjects[0].text!.slice(0, 100)
    : extractedClaims[0]?.slice(0, 100) ?? "";
const claimStatement = firstClaimText
  ? `Media analysis: "${firstClaimText}" — file ${(input.fileHash as string).slice(0, 16)}...`
  : `Media file integrity receipt — SHA-256: ${(input.fileHash as string).slice(0, 16)}...`;

// Primary sources from extracted claims (adapter "manual"; suggested type in metadata)
const claimSources: FrameReceiptPayload["sources"] = [];
for (const claim of claimObjects.slice(0, 5)) {
  for (const ps of (claim.primary_sources ?? []).slice(0, 3)) {
    if (ps.url && ps.label) {
      const id = `claim-src-${createHash("sha256").update(ps.url).digest("hex").slice(0, 16)}`;
      const psExt = ps as ClaimPrimarySource;
      claimSources.push({
        id,
        adapter: "manual",
        url: ps.url,
        title: ps.label,
        retrievedAt: input.timestamp,
        externalRef: ps.url,
        metadata: {
          suggestedSourceType: ps.type ?? "",
          verificationJson: JSON.stringify(psExt.verification ?? null),
        } as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>,
      });
    }
  }
}

const payload: FrameReceiptPayload = {
  schemaVersion: "1.0.0",
  receiptId: randomUUID(),
  createdAt: input.timestamp,
  claims: [
    {
      id: "claim-1",
      statement: claimStatement,
      assertedAt: input.timestamp,
    },
  ],
  sources: [
    {
      id: sourceId,
      adapter: "manual",
      url: `sha256:${input.fileHash}`,
      title: `Media file: ${input.fileName} (${input.contentType})`,
      retrievedAt: input.timestamp,
      externalRef: input.fileHash as string,
      metadata: {
        fileHash: input.fileHash,
        perceptualHash: perceptualHash,
        perceptualHashType: input.perceptualHashType,
        fileName: input.fileName,
        fileSize: input.fileSize,
        contentType: input.contentType,
        detection: input.detection,
        ledgerMatch: ledgerMatch,
        extractedClaimsCount: extractedClaims.length,
      } as unknown as NonNullable<FrameReceiptPayload["sources"][number]["metadata"]>,
    },
    ...claimSources,
  ],
  narrative: narrativeSentences,
  contentHash: "",
};

const signed = signReceipt(payload, { privateKey });
process.stdout.write(`${JSON.stringify(signed)}\n`);
