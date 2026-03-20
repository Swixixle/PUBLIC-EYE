/**
 * Build a live FEC receipt for a candidate and sign it with FRAME_PRIVATE_KEY.
 * Used by the Frame API (Python subprocess). Prints one JSON object to stdout.
 *
 * Set FEC_API_KEY, FRAME_PRIVATE_KEY, and FRAME_PUBLIC_KEY in the environment
 * (e.g. Render dashboard). `apps/api/.env` is not read by this script.
 *
 * Usage: npx tsx scripts/generate-receipt.ts <candidateId>
 */
import { createPrivateKey, createPublicKey } from "node:crypto";
import { buildLiveFecReceipt } from "../packages/sources/index.js";
import { signReceipt, verifyReceipt } from "../packages/signing/index.js";

function pemFromEnv(name: string): string {
  const v = process.env[name];
  if (!v || v.trim() === "") {
    throw new Error(`Missing ${name} in environment`);
  }
  // Handle multiple encoding formats:
  // 1. Literal \n in the string (Render stores it this way)
  // 2. Already has real newlines
  // 3. JSON-encoded string with \\n
  let pem = v;
  if (!pem.includes("\n")) {
    pem = pem.replace(/\\n/g, "\n");
  }
  // Strip surrounding quotes if present
  pem = pem.replace(/^["']|["']$/g, "");
  return pem.trim();
}

const candidateId = process.argv[2]?.trim() ?? "";
if (!candidateId) {
  console.error("Usage: npx tsx scripts/generate-receipt.ts <candidateId>");
  process.exit(1);
}

const fecApiKey = process.env.FEC_API_KEY ?? "DEMO_KEY";

const privatePem = pemFromEnv("FRAME_PRIVATE_KEY");
const publicPem = pemFromEnv("FRAME_PUBLIC_KEY");

const privateKey = createPrivateKey(privatePem);
const envDer = createPublicKey(publicPem).export({
  type: "spki",
  format: "der",
}) as Buffer;
const derivedDer = createPublicKey(privateKey).export({
  type: "spki",
  format: "der",
}) as Buffer;
if (!envDer.equals(derivedDer)) {
  throw new Error(
    "FRAME_PUBLIC_KEY does not match FRAME_PRIVATE_KEY (SPKI DER mismatch).",
  );
}

const payload = await buildLiveFecReceipt(candidateId, fecApiKey);
const signed = signReceipt(payload, { privateKey });

const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}

process.stdout.write(`${JSON.stringify(signed)}\n`);
