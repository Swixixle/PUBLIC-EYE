import { createPrivateKey } from "node:crypto";
import { buildLiveLobbyingReceipt } from "../packages/sources/index.js";
import { signReceipt, verifyReceipt } from "../packages/signing/index.js";

const name = process.argv[2]?.trim() ?? "";
const candidateId = process.argv[3]?.trim() || undefined;

if (!name) {
  console.error(JSON.stringify({ error: "name argument required" }));
  process.exit(1);
}

function getPrivateKeyPem(): string {
  const format = process.env.FRAME_KEY_FORMAT ?? "pem";
  const raw = process.env.FRAME_PRIVATE_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PRIVATE_KEY");
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

const privateKey = createPrivateKey(getPrivateKeyPem());
const payload = await buildLiveLobbyingReceipt(name, candidateId);
const signed = signReceipt(payload, { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
process.stdout.write(`${JSON.stringify(signed)}\n`);
