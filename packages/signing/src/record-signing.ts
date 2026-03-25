import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { etc, getPublicKey, sign, verify, utils } from "@noble/ed25519";

const require = createRequire(import.meta.url);
const canonicalize = require("canonicalize") as (input: unknown) => string | undefined;

/** Noble sync Ed25519 requires SHA-512 wired to Node (RFC 8032). */
etc.sha512Sync = (...messages: Uint8Array[]) => {
  const h = createHash("sha512");
  for (const m of messages) h.update(m);
  return new Uint8Array(h.digest());
};

function jcsRecord(value: unknown): string {
  const out = canonicalize(value);
  if (typeof out !== "string") {
    throw new TypeError("JCS canonicalization failed for value");
  }
  return out;
}

/** Signing payload: strip signature metadata so the digest is stable and never self-referential. */
export function recordBodyForSigning(record: object): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...(record as Record<string, unknown>) };
  delete copy.signature;
  delete copy.signed_at;
  delete copy.public_key;
  return copy;
}

function bytesToHex(b: Uint8Array): string {
  return Buffer.from(b).toString("hex");
}

function hexToBytes(hex: string): Uint8Array {
  const s = hex.trim();
  if (s.length % 2 !== 0) throw new Error("invalid hex length");
  return new Uint8Array(Buffer.from(s, "hex"));
}

/** 32-byte Ed25519 secret seed + 32-byte public key, both hex. */
export function generateKeypair(): { privateKey: string; publicKey: string } {
  const priv = utils.randomPrivateKey();
  const pub = getPublicKey(priv);
  return { privateKey: bytesToHex(priv), publicKey: bytesToHex(pub) };
}

export interface SignRecordResult {
  signature: string;
  signed_at: string;
  public_key: string;
}

/**
 * Signs JCS( record without `signature` | `signed_at` | `public_key` ) with Ed25519.
 * Message is UTF-8 bytes of the canonical JSON string (RFC 8785).
 */
export function signRecord(record: object, privateKeyHex: string): SignRecordResult {
  const priv = hexToBytes(privateKeyHex);
  if (priv.length !== 32) {
    throw new Error("privateKey must be a 64-character hex string (32 bytes)");
  }
  const pub = getPublicKey(priv);
  const body = recordBodyForSigning(record);
  const msg = new TextEncoder().encode(jcsRecord(body));
  const sig = sign(msg, priv);
  return {
    signature: bytesToHex(sig),
    signed_at: new Date().toISOString(),
    public_key: bytesToHex(pub),
  };
}

/** Verifies Ed25519 signature over the same JCS payload as signing. */
export function verifyRecord(record: object, signatureHex: string, publicKeyHex: string): boolean {
  try {
    const body = recordBodyForSigning(record);
    const msg = new TextEncoder().encode(jcsRecord(body));
    const sig = hexToBytes(signatureHex);
    const pub = hexToBytes(publicKeyHex);
    if (sig.length !== 64 || pub.length !== 32) return false;
    return verify(sig, msg, pub);
  } catch {
    return false;
  }
}
