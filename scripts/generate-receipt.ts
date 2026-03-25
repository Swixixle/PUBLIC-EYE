import { createPublicKey } from "node:crypto";
import { buildLiveFecReceipt } from "../packages/sources/index.js";
import {
  loadFramePrivateKeyFromEnv,
  loadFramePublicKeyFromEnv,
  signReceipt,
  verifyReceipt,
} from "../packages/signing/dist/index.js";

const candidateId = process.argv[2]?.trim() ?? "";
if (!candidateId) {
  console.error("Usage: npx tsx scripts/generate-receipt.ts <candidateId>");
  process.exit(1);
}

const fecApiKey = process.env.FEC_API_KEY ?? "DEMO_KEY";
const privateKey = loadFramePrivateKeyFromEnv();
const publicFromEnv = loadFramePublicKeyFromEnv();

const envDer = publicFromEnv.export({ type: "spki", format: "der" }) as Buffer;
const derivedDer = createPublicKey(privateKey).export({ type: "spki", format: "der" }) as Buffer;
if (!envDer.equals(derivedDer)) {
  throw new Error("FRAME_PUBLIC_KEY does not match FRAME_PRIVATE_KEY (SPKI DER mismatch).");
}

const payload = await buildLiveFecReceipt(candidateId, fecApiKey);
const signed = signReceipt(payload, { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
process.stdout.write(`${JSON.stringify(signed)}\n`);
