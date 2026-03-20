import { createPrivateKey, createPublicKey } from "node:crypto";
import { buildLiveFecReceipt } from "../packages/sources/index.js";
import { signReceipt, verifyReceipt } from "../packages/signing/index.js";

function getPrivateKeyPem(): string {
  const format = process.env.FRAME_KEY_FORMAT ?? "pem";
  const raw = process.env.FRAME_PRIVATE_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PRIVATE_KEY in environment");
  if (format === "base64") {
    const decoded = Buffer.from(raw.trim(), "base64").toString("utf8");
    return decoded.replace(/\\n/g, "\n");
  }
  let pem = raw;
  if (!pem.includes("\n")) {
    pem = pem.replace(/\\n/g, "\n");
  }
  pem = pem.replace(/^["']|["']$/g, "");
  return pem.trim();
}

function getPublicKeyPem(): string {
  const format = process.env.FRAME_KEY_FORMAT ?? "pem";
  const raw = process.env.FRAME_PUBLIC_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PUBLIC_KEY in environment");
  if (format === "base64") {
    const decoded = Buffer.from(raw.trim(), "base64").toString("utf8");
    return decoded.replace(/\\n/g, "\n");
  }
  let pem = raw;
  pem = pem.replace(/\\n/g, "\n");
  pem = pem.replace(/^["']|["']$/g, "");
  return pem.trim();
}

const candidateId = process.argv[2]?.trim() ?? "";
if (!candidateId) {
  console.error("Usage: npx tsx scripts/generate-receipt.ts <candidateId>");
  process.exit(1);
}

const fecApiKey = process.env.FEC_API_KEY ?? "DEMO_KEY";
const privatePem = getPrivateKeyPem();
const publicPem = getPublicKeyPem();
process.stderr.write(`DEBUG key format: ${process.env.FRAME_KEY_FORMAT}\n`);
process.stderr.write(`DEBUG raw length: ${process.env.FRAME_PRIVATE_KEY?.length}\n`);
process.stderr.write(`DEBUG pem starts: ${privatePem.slice(0, 40)}\n`);
process.stderr.write(`DEBUG pem ends: ${privatePem.slice(-40)}\n`);
const privateKey = createPrivateKey(privatePem);

const envDer = createPublicKey(publicPem).export({ type: "spki", format: "der" }) as Buffer;
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
