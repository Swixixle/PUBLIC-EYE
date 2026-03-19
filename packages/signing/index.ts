import {
  createHash,
  createPublicKey,
  sign as cryptoSign,
  verify as cryptoVerify,
  type KeyObject,
} from "node:crypto";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const canonicalize = require("canonicalize") as (input: unknown) => string | undefined;
import type { FrameReceiptPayload, FrameSignedReceipt } from "@frame/types";

/** Omitted from `contentHash` preimage (verification metadata / self-referential fields). */
const CONTENT_HASH_EXCLUDE = new Set(["contentHash", "signature", "publicKey"]);

/** Stable key order is defined by JCS (RFC 8785); do not use JSON.stringify for hashing. */
export function jcsCanonicalize(value: unknown): string {
  const out = canonicalize(value);
  if (typeof out !== "string") {
    throw new TypeError("JCS canonicalization failed for value");
  }
  return out;
}

export function sha256HexOfJcs(value: unknown): string {
  const json = jcsCanonicalize(value);
  return createHash("sha256").update(json, "utf8").digest("hex");
}

/**
 * Builds the object that is hashed to produce `contentHash`
 * (all receipt fields except `contentHash` and `signature`).
 */
export function receiptBodyForContentHash(payload: object): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...(payload as Record<string, unknown>) };
  for (const k of CONTENT_HASH_EXCLUDE) delete copy[k];
  return copy;
}

export function computeContentHash(payload: object): string {
  const body = receiptBodyForContentHash(payload);
  return sha256HexOfJcs(body);
}

/**
 * Canonical signing input: full receipt including `contentHash`, excluding only `signature`.
 */
export function receiptBodyForSigning(payload: object): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...(payload as Record<string, unknown>) };
  delete copy.signature;
  return copy;
}

export function signingDigest(payload: object): Buffer {
  const body = receiptBodyForSigning(payload);
  const json = jcsCanonicalize(body);
  return createHash("sha256").update(json, "utf8").digest();
}

export interface SignReceiptOptions {
  privateKey: KeyObject;
  /** If false, caller must set a correct `contentHash` on the payload first. */
  assignContentHash?: boolean;
}

/**
 * Signs a receipt with Ed25519. The message is SHA-256( JCS( payload without signature ) ).
 */
export function signReceipt(
  payload: FrameReceiptPayload,
  opts: SignReceiptOptions,
): FrameSignedReceipt {
  const assign = opts.assignContentHash !== false;
  let working: FrameReceiptPayload = { ...payload };
  if (assign) {
    const hash = computeContentHash(working);
    working = { ...working, contentHash: hash };
  }

  const publicKey = extractPublicKeyBase64(opts.privateKey);
  const withPub: Record<string, unknown> = { ...working, publicKey };

  const digest = signingDigest(withPub);
  const sigBuf = cryptoSign(null, digest, opts.privateKey);
  const signature = Buffer.from(sigBuf).toString("base64");

  return {
    ...working,
    publicKey,
    signature,
  } as FrameSignedReceipt;
}

function extractPublicKeyBase64(privateKey: KeyObject): string {
  const pub = createPublicKey(privateKey);
  const der = pub.export({ type: "spki", format: "der" }) as Buffer;
  return der.toString("base64");
}

export interface VerifyReceiptResult {
  ok: boolean;
  reasons: string[];
}

/**
 * Verifies `contentHash` and Ed25519 signature using JCS for all canonicalization steps.
 */
export function verifyReceipt(receipt: FrameSignedReceipt): VerifyReceiptResult {
  const reasons: string[] = [];

  const expectedHash = computeContentHash(receipt);
  if (expectedHash !== receipt.contentHash) {
    reasons.push("contentHash does not match JCS payload");
  }

  const digest = signingDigest(receipt);

  let pubDer: Buffer;
  try {
    pubDer = Buffer.from(receipt.publicKey, "base64");
  } catch {
    reasons.push("publicKey is not valid base64");
    return { ok: false, reasons };
  }

  const okSig = cryptoVerify(
    null,
    digest,
    { key: pubDer, format: "der", type: "spki" },
    Buffer.from(receipt.signature, "base64"),
  );
  if (!okSig) reasons.push("signature verification failed");

  return { ok: reasons.length === 0, reasons };
}
