import { buildWikidataReceipt } from "../packages/sources/index.js";
import {
  loadFramePrivateKeyFromEnv,
  signReceipt,
  verifyReceipt,
} from "../packages/signing/dist/index.js";

const personName = process.argv[2]?.trim() ?? "";
const wikidataId = process.argv[3]?.trim() || undefined;

if (!personName) {
  console.error(JSON.stringify({ error: "personName required" }));
  process.exit(1);
}

const privateKey = loadFramePrivateKeyFromEnv();
const payload = await buildWikidataReceipt(personName, wikidataId);
const signed = signReceipt(payload, { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
process.stdout.write(`${JSON.stringify(signed)}\n`);
