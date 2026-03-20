import { createPrivateKey } from "node:crypto";
import { buildCombinedPoliticianReceipt } from "../packages/sources/index.js";
import { signReceipt, verifyReceipt } from "../packages/signing/index.js";

const candidateId = process.argv[2]?.trim() ?? "";
const lobbyingClients: string[] = JSON.parse(process.argv[3] ?? "[]");
const years: number[] = JSON.parse(process.argv[4] ?? "[]");
const fecKey = process.argv[5]?.trim() ?? "DEMO_KEY";

if (!candidateId) {
  console.error(JSON.stringify({ error: "candidateId required" }));
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
const payload = await buildCombinedPoliticianReceipt(
  candidateId,
  lobbyingClients,
  years,
  fecKey,
);
const signed = signReceipt(payload, { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
process.stdout.write(`${JSON.stringify(signed)}\n`);
