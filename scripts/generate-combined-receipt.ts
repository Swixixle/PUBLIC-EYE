import { buildCombinedPoliticianReceipt } from "../packages/sources/index.js";
import {
  loadFramePrivateKeyFromEnv,
  signReceipt,
  verifyReceipt,
} from "../packages/signing/dist/index.js";

const candidateId = process.argv[2]?.trim() ?? "";
const lobbyingClients: string[] = JSON.parse(process.argv[3] ?? "[]");
const years: number[] = JSON.parse(process.argv[4] ?? "[]");
const fecKey = process.argv[5]?.trim() ?? "DEMO_KEY";

if (!candidateId) {
  console.error(JSON.stringify({ error: "candidateId required" }));
  process.exit(1);
}

const privateKey = loadFramePrivateKeyFromEnv();
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
